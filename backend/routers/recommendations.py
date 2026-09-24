from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.problem_catalog import (
    CANONICAL_TOPICS,
    canonicalize_topics,
    is_english_problem,
    normalize_difficulty,
)
from backend.models import CodingAttempt, Problem, User, UserProfile
from backend.routers.auth import get_current_user
from backend.routers.problems import _catalog_rows


_VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

TOPICS = CANONICAL_TOPICS

def _naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value

@router.get("/next")
def next_recommendation(
    current_problem_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    # Use the exact same cleaned catalogue as Practice: English problems,
    # supported difficulty, canonical topic names.
    catalog = _catalog_rows(db)
    catalog_by_id = {int(row["id"]): row for row in catalog}

    attempts = (
        db.query(CodingAttempt, Problem)
        .join(Problem, CodingAttempt.problem_id == Problem.id)
        .filter(CodingAttempt.user_id == current_user.id)
        .all()
    )

    solved_ids = {
        attempt.problem_id
        for attempt, _problem in attempts
        if attempt.problem_id in catalog_by_id
        and attempt.mode == "submit"
        and attempt.status == "Accepted"
    }

    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent_ids = {
        attempt.problem_id
        for attempt, _problem in attempts
        if attempt.problem_id in catalog_by_id
        and _naive_utc(attempt.created_at) >= _naive_utc(recent_cutoff)
    }

    topic_stats = defaultdict(lambda: {"attempted": 0, "accepted": 0, "failures": 0})
    for attempt, problem in attempts:
        catalog_problem = catalog_by_id.get(problem.id)
        if not catalog_problem:
            continue
        for topic in catalog_problem["topics"]:
            topic_stats[topic]["attempted"] += 1
            if attempt.mode == "submit" and attempt.status == "Accepted":
                topic_stats[topic]["accepted"] += 1
            elif attempt.mode == "submit":
                topic_stats[topic]["failures"] += 1

    def topic_health(topic: str) -> float:
        stat = topic_stats[topic]
        if not stat["attempted"]:
            return 0.55
        acceptance = stat["accepted"] / max(stat["attempted"], 1)
        failure_pressure = min(stat["failures"] / max(stat["attempted"], 1), 1.0)
        return max(0.0, min(1.0, 0.7 - acceptance * 0.45 + failure_pressure * 0.35))

    experience = (profile.experience_level if profile else "Beginner") or "Beginner"
    preferred_difficulty = {
        "Beginner": "Easy",
        "Intermediate": "Medium",
        "Advanced": "Medium",
    }.get(experience, "Medium")

    # Keep the active recommendation stable until that exact problem is solved.
    if current_problem_id is not None:
        current_problem = catalog_by_id.get(current_problem_id)
        if current_problem is not None and current_problem_id not in solved_ids:
            current_topics = list(current_problem["topics"])
            current_weak_topic = min(
                current_topics,
                key=lambda topic: topic_health(topic),
                default=current_topics[0] if current_topics else "General DSA",
            )
            return {
                "problem": {
                    "id": current_problem["id"],
                    "slug": current_problem["slug"],
                    "title": current_problem["title"],
                    "difficulty": current_problem["difficulty"],
                    "topics": current_topics,
                },
                "reason": (
                    "Keep working on this problem. A new recommendation will appear after you solve it."
                    if not current_topics
                    else f"Keep working on this problem to strengthen {current_weak_topic}. "
                         "A new recommendation will appear after you solve it."
                ),
                "focus_topic": current_weak_topic,
                "score": None,
                "topic_health": round(topic_health(current_weak_topic), 3),
                "is_reinforcement": False,
                "locked_until_solved": True,
                "profile_experience": experience,
            }

    scored = []
    for problem in catalog:
        problem_id = int(problem["id"])
        if problem_id in solved_ids:
            continue

        topics = list(problem["topics"])
        weakness = sum(topic_health(topic) for topic in topics) / max(len(topics), 1)
        difficulty = problem["difficulty"]
        difficulty_bonus = 1.0 if difficulty == preferred_difficulty else 0.35
        recent_penalty = 0.45 if problem_id in recent_ids else 0.0
        exploration_bonus = 0.25 if not any(topic in topic_stats for topic in topics) else 0.0
        score = weakness * 5.0 + difficulty_bonus * 2.0 + 3.0 + exploration_bonus - recent_penalty
        scored.append((score, problem, weakness))

    if not scored:
        return {
            "problem": None,
            "reason": "You have solved every currently available problem.",
            "focus_topic": None,
            "score": None,
            "topic_health": None,
            "is_reinforcement": False,
            "locked_until_solved": False,
            "profile_experience": experience,
        }

    scored.sort(key=lambda item: (-item[0], int(item[1]["id"])))
    chosen_score, chosen, chosen_weakness = scored[0]
    chosen_topics = list(chosen["topics"])
    weak_topic = min(
        chosen_topics,
        key=lambda topic: topic_health(topic),
        default=chosen_topics[0] if chosen_topics else "General DSA",
    )

    reason = (
        f"Recommended because {weak_topic} is currently one of your less-practiced or less-stable areas."
        if chosen_topics
        else "Recommended as a fresh problem from the current Practice library."
    )

    return {
        "problem": {
            "id": chosen["id"],
            "slug": chosen["slug"],
            "title": chosen["title"],
            "difficulty": chosen["difficulty"],
            "topics": chosen_topics,
        },
        "reason": reason,
        "focus_topic": weak_topic,
        "score": round(chosen_score, 3),
        "topic_health": round(chosen_weakness, 3),
        "is_reinforcement": False,
        "locked_until_solved": False,
        "profile_experience": experience,
    }

@router.get("/roadmap")
def learning_roadmap(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Build a roadmap only from topics that have real Practice questions."""
    catalog = _catalog_rows(db)
    catalog_by_id = {int(row["id"]): row for row in catalog}

    available_topic_counts = defaultdict(int)
    for row in catalog:
        for topic in row["topics"]:
            available_topic_counts[topic] += 1

    available_topics = [topic for topic in TOPICS if available_topic_counts[topic] > 0]

    attempts = (
        db.query(CodingAttempt, Problem)
        .join(Problem, CodingAttempt.problem_id == Problem.id)
        .filter(CodingAttempt.user_id == current_user.id)
        .all()
    )

    stats = defaultdict(lambda: {
        "problem_ids": set(),
        "solved_problem_ids": set(),
        "submissions": 0,
        "accepted": 0,
    })
    for attempt, problem in attempts:
        catalog_problem = catalog_by_id.get(problem.id)
        if not catalog_problem:
            continue
        for topic in catalog_problem["topics"]:
            stats[topic]["problem_ids"].add(problem.id)
            if attempt.mode == "submit":
                stats[topic]["submissions"] += 1
                if attempt.status == "Accepted":
                    stats[topic]["accepted"] += 1
                    stats[topic]["solved_problem_ids"].add(problem.id)

    def mastery(topic: str) -> float:
        stat = stats[topic]
        attempted = len(stat["problem_ids"])
        solved = len(stat["solved_problem_ids"])
        if not attempted:
            return 0.0

        evidence = min(1.0, attempted / 10.0)
        solve_rate = solved / attempted
        acceptance = stat["accepted"] / max(stat["submissions"], 1)
        return round((0.70 * solve_rate + 0.30 * acceptance) * evidence * 100)

    rows = []
    for topic in available_topics:
        stat = stats[topic]
        attempted = len(stat["problem_ids"])
        solved = len(stat["solved_problem_ids"])
        value = mastery(topic)

        if value >= 75 and attempted >= 3:
            status = "mastered"
        elif attempted > 0:
            status = "in_progress"
        else:
            status = "not_started"

        priority = (
            (100 - value) * 1.5
            + (25 if status == "in_progress" else 12)
            + (8 if status == "not_started" else 0)
            + min(10, available_topic_counts[topic] / 10)
        )

        rows.append({
            "topic": topic,
            "status": status,
            "mastery": value,
            "attempted_problems": attempted,
            "solved_problems": solved,
            "available_problems": available_topic_counts[topic],
            "acceptance_rate": round(
                stat["accepted"] / stat["submissions"] * 100
            ) if stat["submissions"] else 0,
            "priority": round(priority, 2),
        })

    mastered = sorted(
        [row for row in rows if row["status"] == "mastered"],
        key=lambda row: (-row["mastery"], row["topic"]),
    )[:3]
    active = sorted(
        [row for row in rows if row["status"] != "mastered"],
        key=lambda row: (-row["priority"], row["topic"]),
    )[:7]

    roadmap = mastered[::-1] + active
    for index, row in enumerate(roadmap):
        if row["status"] == "mastered":
            row["position"] = "completed"
        elif index == len(mastered):
            row["position"] = "current"
        else:
            row["position"] = "up_next"

    return {
        "items": roadmap,
        "current_topic": next(
            (row["topic"] for row in roadmap if row["position"] == "current"),
            None,
        ),
        "available_topic_count": len(available_topics),
    }

@router.get("/weak")
def weak_topics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attempts = (
        db.query(CodingAttempt, Problem)
        .join(Problem, CodingAttempt.problem_id == Problem.id)
        .filter(CodingAttempt.user_id == current_user.id)
        .all()
    )
    stats = defaultdict(lambda: {"attempted": 0, "accepted": 0, "failures": 0})
    for attempt, problem in attempts:
        if attempt.mode != "submit":
            continue
        for topic in problem.topics or []:
            stats[topic]["attempted"] += 1
            if attempt.status == "Accepted":
                stats[topic]["accepted"] += 1
            else:
                stats[topic]["failures"] += 1

    result = []
    for topic in TOPICS:
        stat = stats[topic]
        if not stat["attempted"]:
            continue
        acceptance = round(stat["accepted"] / stat["attempted"] * 100)
        result.append({
            "topic": topic,
            "submissions": stat["attempted"],
            "accepted": stat["accepted"],
            "failures": stat["failures"],
            "acceptance_rate": acceptance,
            "priority": round(100 - acceptance),
        })
    result.sort(key=lambda item: (-item["priority"], -item["submissions"], item["topic"]))
    return {"items": result[:5]}