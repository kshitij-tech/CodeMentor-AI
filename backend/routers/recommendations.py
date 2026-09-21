from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import CodingAttempt, Problem, User, UserProfile
from backend.routers.auth import get_current_user


_VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

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

def _naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value

@router.get("/next")
def next_recommendation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    attempts = (
        db.query(CodingAttempt, Problem)
        .join(Problem, CodingAttempt.problem_id == Problem.id)
        .filter(CodingAttempt.user_id == current_user.id)
        .all()
    )
    problems = (
        db.query(Problem)
        .filter(Problem.difficulty.in_(_VALID_DIFFICULTIES))
        .order_by(Problem.id.asc())
        .all()
    )

    solved_ids = {
        attempt.problem_id
        for attempt, _ in attempts
        if attempt.mode == "submit" and attempt.status == "Accepted"
    }
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent_ids = {
        attempt.problem_id
        for attempt, _ in attempts
        if _naive_utc(attempt.created_at) >= _naive_utc(recent_cutoff)
    }

    topic_stats = defaultdict(lambda: {"attempted": 0, "accepted": 0, "failures": 0})
    for attempt, problem in attempts:
        for topic in problem.topics or []:
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

    scored = []
    for problem in problems:
        topics = problem.topics or []
        weakness = sum(topic_health(topic) for topic in topics) / max(len(topics), 1)
        difficulty_bonus = 1.0 if problem.difficulty == preferred_difficulty else 0.35
        unsolved_bonus = 1.0 if problem.id not in solved_ids else 0.0
        recent_penalty = 0.45 if problem.id in recent_ids else 0.0
        exploration_bonus = 0.25 if not any(topic in topic_stats for topic in topics) else 0.0
        score = weakness * 5.0 + difficulty_bonus * 2.0 + unsolved_bonus * 3.0 + exploration_bonus - recent_penalty
        scored.append((score, problem, weakness))

    scored.sort(key=lambda item: (-item[0], item[1].id))
    chosen_score, chosen, chosen_weakness = scored[0]
    chosen_topics = chosen.topics or []
    weak_topic = min(
        chosen_topics,
        key=lambda topic: topic_health(topic),
        default=chosen_topics[0] if chosen_topics else "General DSA",
    )
    was_solved = chosen.id in solved_ids
    reason = (
        f"Recommended because {weak_topic} is currently one of your less-practiced or less-stable areas."
        if chosen_topics
        else "Recommended as a fresh problem from the current problem set."
    )
    if was_solved:
        reason = f"Recommended as a reinforcement problem because {weak_topic} needs more practice."

    return {
        "problem": {
            "id": chosen.id,
            "slug": chosen.slug,
            "title": chosen.title,
            "difficulty": chosen.difficulty,
            "topics": chosen_topics,
        },
        "reason": reason,
        "focus_topic": weak_topic,
        "score": round(chosen_score, 3),
        "topic_health": round(chosen_weakness, 3),
        "is_reinforcement": was_solved,
        "profile_experience": experience,
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