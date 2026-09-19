from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import CodingAttempt, MentorMessage, Problem, User
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["Analytics"])

TOPICS = [
    "Arrays & Strings",
    "Hashing & Hash Maps",
    "Two Pointers",
    "Binary Search",
    "Linked Lists",
    "Trees & BST",
    "Graphs (BFS/DFS)",
    "Dynamic Programming",
    "Backtracking",
    "Greedy Algorithms",
]

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value

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
        for attempt in attempts
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

    mentor_hints = (
        db.query(MentorMessage)
        .filter(
            MentorMessage.role == "assistant",
            MentorMessage.action == "hint",
        )
        .join(
            # mentor_sessions is intentionally joined through the FK path below
            # using the session id without requiring ORM relationships.
            # SQLAlchemy accepts the explicit join condition.
        )
    )

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
        topic_attempts = [pair for pair in attempts if topic in (pair[1].topics or [])]
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
        topic_accepted = [attempt for attempt in topic_submissions if attempt.status == "Accepted"]
        mastery = round((len(topic_solved_ids) / len(topic_problem_ids)) * 100) if topic_problem_ids else 0
        acceptance = round((len(topic_accepted) / len(topic_submissions)) * 100) if topic_submissions else 0
        topic_stats.append({
            "topic": topic,
            "attempted_problems": len(topic_problem_ids),
            "solved_problems": len(topic_solved_ids),
            "submissions": len(topic_submissions),
            "acceptance_rate": acceptance,
            "mastery": mastery,
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