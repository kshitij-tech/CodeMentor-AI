from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.problem_catalog import CANONICAL_TOPICS, canonicalize_topics, normalize_difficulty
from backend.models import CodingAttempt, MentorMessage, Problem, User
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["Analytics"])

TOPICS = CANONICAL_TOPICS

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value

def _problem_matches_topic(problem: Problem, topic: str) -> bool:
    return topic in canonicalize_topics(problem.topics)


@router.get("/summary")
def analytics_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attempts = (
        db.query(CodingAttempt, Problem)
        .join(Problem, CodingAttempt.problem_id == Problem.id)
        .filter(CodingAttempt.user_id == current_user.id)
        .order_by(CodingAttempt.created_at.asc())
        .all()
    )

    submissions = [attempt for attempt, _ in attempts if attempt.mode == "submit"]
    accepted_submissions = [attempt for attempt in submissions if attempt.status == "Accepted"]
    solved_problem_ids = {attempt.problem_id for attempt in accepted_submissions}

    runtimes = [
        result.get("runtime_ms")
        for attempt, _ in attempts
        for result in (attempt.results or [])
        if isinstance(result, dict) and isinstance(result.get("runtime_ms"), (int, float))
    ]

    now = _utc_now()
    seven_days_ago = _naive_utc(now - timedelta(days=7))
    recent = [attempt for attempt, _ in attempts if _naive_utc(attempt.created_at) >= seven_days_ago]
    recent_solved = {attempt.problem_id for attempt in recent if attempt.mode == "submit" and attempt.status == "Accepted"}
    recent_active_days = {
        _naive_utc(attempt.created_at).date().isoformat()
        for attempt in recent
    }

    # Count hints through a lightweight SQL query without adding ORM relationships.
    from sqlalchemy import func
    from backend.models import MentorSession
    hint_count = (
        db.query(func.count(MentorMessage.id))
        .join(MentorSession, MentorMessage.session_id == MentorSession.id)
        .filter(
            MentorSession.user_id == current_user.id,
            MentorMessage.role == "assistant",
            MentorMessage.action == "hint",
        )
        .scalar()
        or 0
    )

    topic_stats = []
    for topic in TOPICS:
        topic_attempts = [pair for pair in attempts if _problem_matches_topic(pair[1], topic)]
        topic_problem_ids = {problem.id for _, problem in topic_attempts}
        topic_solved_ids = {
            attempt.problem_id
            for attempt, problem in topic_attempts
            if attempt.mode == "submit" and attempt.status == "Accepted"
        }
        topic_submissions = [
            attempt
            for attempt, _ in topic_attempts
            if attempt.mode == "submit"
        ]
        topic_accepted = [
            attempt for attempt in topic_submissions
            if attempt.status == "Accepted"
        ]

        attempted_count = len(topic_problem_ids)
        solved_count = len(topic_solved_ids)
        submission_count = len(topic_submissions)
        acceptance = (
            round((len(topic_accepted) / submission_count) * 100)
            if submission_count else 0
        )

        # Mastery is an evidence-weighted skill estimate, not simply
        # solved/attempted. A single successful problem therefore cannot
        # produce 100%. The evidence factor grows with distinct problems
        # practiced and reaches full weight after 10 distinct problems.
        solve_rate = (solved_count / attempted_count) if attempted_count else 0.0
        submission_success = (len(topic_accepted) / submission_count) if submission_count else 0.0
        evidence = min(1.0, attempted_count / 10.0)
        raw_mastery = (0.70 * solve_rate + 0.30 * submission_success) * 100
        mastery = round(raw_mastery * evidence) if attempted_count else 0

        topic_stats.append({
            "topic": topic,
            "attempted_problems": attempted_count,
            "solved_problems": solved_count,
            "submissions": submission_count,
            "acceptance_rate": acceptance,
            "mastery": mastery,
            "mastery_confidence": round(evidence * 100),
        })

    daily = []
    for offset in range(6, -1, -1):
        day = (now - timedelta(days=offset)).date()
        day_attempts = [
            attempt for attempt, _ in attempts
            if _naive_utc(attempt.created_at).date() == day
        ]
        daily.append({
            "date": day.isoformat(),
            "attempts": len(day_attempts),
            "solved": len({
                attempt.problem_id for attempt in day_attempts
                if attempt.mode == "submit" and attempt.status == "Accepted"
            }),
        })

    return {
        "total_attempts": len(attempts),
        "total_submissions": len(submissions),
        "accepted_submissions": len(accepted_submissions),
        "total_solved": len(solved_problem_ids),
        "acceptance_rate": round((len(accepted_submissions) / len(submissions)) * 100) if submissions else 0,
        "solved_last_7_days": len(recent_solved),
        "active_days_last_7_days": len(recent_active_days),
        "velocity_pace": round(len(recent_solved) / max(len(recent_active_days), 1), 1),
        "ai_hints": int(hint_count),
        "average_runtime_ms": round(sum(runtimes) / len(runtimes), 1) if runtimes else None,
        "topics": topic_stats,
        "daily": daily,
    }

@router.get("/detail")
def analytics_detail(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    summary = analytics_summary(current_user=current_user, db=db)

    rows = (
        db.query(CodingAttempt, Problem)
        .join(Problem, CodingAttempt.problem_id == Problem.id)
        .filter(CodingAttempt.user_id == current_user.id)
        .order_by(CodingAttempt.created_at.desc())
        .all()
    )

    problem_map = {}
    history = []
    for attempt, problem in rows:
        runtimes = [
            result.get("runtime_ms")
            for result in (attempt.results or [])
            if isinstance(result, dict) and isinstance(result.get("runtime_ms"), (int, float))
        ]
        problem_key = problem.id
        if problem_key not in problem_map:
            problem_map[problem_key] = {
                "problem_id": problem.id,
                "slug": problem.slug,
                "title": problem.title,
                "difficulty": problem.difficulty,
                "topics": problem.topics or [],
                "attempts": 0,
                "submissions": 0,
                "accepted_submissions": 0,
                "last_status": attempt.status,
                "latest_attempt_at": _naive_utc(attempt.created_at).isoformat(),
            }
        stat = problem_map[problem_key]
        stat["attempts"] += 1
        if attempt.mode == "submit":
            stat["submissions"] += 1
            if attempt.status == "Accepted":
                stat["accepted_submissions"] += 1

        history.append({
            "attempt_id": attempt.id,
            "problem_slug": problem.slug,
            "problem_title": problem.title,
            "difficulty": problem.difficulty,
            "topics": problem.topics or [],
            "language": attempt.language,
            "mode": attempt.mode,
            "status": attempt.status,
            "summary": attempt.summary,
            "runtime_ms": round(sum(runtimes) / len(runtimes), 1) if runtimes else None,
            "created_at": _naive_utc(attempt.created_at).isoformat(),
        })

    for stat in problem_map.values():
        stat["acceptance_rate"] = (
            round((stat["accepted_submissions"] / stat["submissions"]) * 100)
            if stat["submissions"]
            else 0
        )

    return {
        **summary,
        "problems": list(problem_map.values()),
        "history": history[:100],
    }
