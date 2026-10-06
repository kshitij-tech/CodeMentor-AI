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

ROADMAP_PREREQUISITES = {
    "Arrays": [], "Strings": ["Arrays"], "Hashing": ["Arrays"], "Sorting": ["Arrays"],
    "Prefix Sum": ["Arrays"], "Math": ["Arrays"], "Recursion": ["Arrays"],
    "Two Pointers": ["Arrays", "Sorting"], "Sliding Window": ["Arrays", "Two Pointers"],
    "Binary Search": ["Arrays", "Sorting"], "Stack": ["Arrays"], "Queue": ["Arrays", "Stack"],
    "Linked List": ["Arrays"], "Intervals": ["Arrays", "Sorting"], "Bit Manipulation": ["Arrays"],
    "Trees": ["Stack", "Recursion"], "BST": ["Trees", "Binary Search"],
    "Heap/Priority Queue": ["Trees"], "Backtracking": ["Trees", "Recursion"],
    "Greedy": ["Sorting", "Prefix Sum"], "Graphs": ["Trees"], "DFS": ["Graphs"], "BFS": ["Graphs"],
    "Dynamic Programming": ["Arrays", "Prefix Sum"], "Trie": ["Strings"], "Union Find": ["Graphs"],
    "Topological Sort": ["Graphs"], "Divide and Conquer": ["Recursion"],
    "Monotonic Stack": ["Stack"], "Monotonic Queue": ["Queue"], "Matrix": ["Arrays"],
    "Implementation": ["Arrays"], "Brute Force": ["Arrays"],
    "Constructive Algorithms": ["Arrays"], "Number Theory": ["Math"],
    "Combinatorics": ["Math"], "Geometry": ["Math"], "Probability": ["Math"],
    "Game Theory": ["Math"], "Meet in the Middle": ["Brute Force"],
}

ROADMAP_TIER = {
    "Arrays": 1, "Strings": 1, "Hashing": 1, "Sorting": 1, "Prefix Sum": 1, "Math": 1,
    "Recursion": 1, "Implementation": 1, "Brute Force": 2, "Constructive Algorithms": 2,
    "Number Theory": 2, "Combinatorics": 2, "Geometry": 2, "Probability": 3, "Game Theory": 3,
    "Two Pointers": 2, "Sliding Window": 2, "Binary Search": 2, "Stack": 2, "Queue": 2,
    "Linked List": 2, "Intervals": 2, "Bit Manipulation": 2, "Matrix": 2,
    "Trees": 3, "BST": 3, "Heap/Priority Queue": 3, "Backtracking": 3, "Greedy": 3,
    "Trie": 3, "Divide and Conquer": 3, "Monotonic Stack": 3, "Meet in the Middle": 3,
    "Graphs": 4, "DFS": 4, "BFS": 4, "Dynamic Programming": 4,
    "Union Find": 4, "Topological Sort": 4, "Monotonic Queue": 3,
}


EXPERIENCE_TARGET_TIER = {
    "Beginner": 1,
    "Intermediate": 2,
    "Advanced": 3,
}

ROADMAP_MASTERY_UNLOCK = 60
ROADMAP_MIN_EVIDENCE = 3
ROADMAP_MASTERED = 75


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
    """Build an evidence-driven prerequisite roadmap from the real Practice catalogue."""
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    experience = (profile.experience_level if profile else "Beginner") or "Beginner"
    target_tier = EXPERIENCE_TARGET_TIER.get(experience, 1)

    catalog = _catalog_rows(db)
    catalog_by_id = {int(row["id"]): row for row in catalog}

    available_topic_counts = defaultdict(int)
    difficulty_counts = defaultdict(lambda: defaultdict(int))
    for row in catalog:
        for topic in row["topics"]:
            available_topic_counts[topic] += 1
            difficulty_counts[topic][row["difficulty"]] += 1

    available_topics = [
        topic for topic in TOPICS
        if available_topic_counts[topic] > 0
    ]
    available_set = set(available_topics)

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

    def topic_mastery(topic: str) -> int:
        stat = stats[topic]
        attempted = len(stat["problem_ids"])
        solved = len(stat["solved_problem_ids"])
        if not attempted:
            return 0
        evidence = min(1.0, attempted / 10.0)
        solve_rate = solved / attempted
        acceptance = stat["accepted"] / max(stat["submissions"], 1)
        return round((0.70 * solve_rate + 0.30 * acceptance) * evidence * 100)

    def is_mastered(topic: str) -> bool:
        stat = stats[topic]
        return (
            topic_mastery(topic) >= ROADMAP_MASTERED
            and len(stat["problem_ids"]) >= ROADMAP_MIN_EVIDENCE
        )

    def prerequisite_topics(topic: str) -> list[str]:
        # Only catalogue topics matter. A prerequisite that is absent from
        # Practice cannot reasonably block a learner.
        return [
            item for item in ROADMAP_PREREQUISITES.get(topic, [])
            if item in available_set
        ]

    def prerequisites_met(topic: str) -> bool:
        return all(
            is_mastered(prerequisite)
            for prerequisite in prerequisite_topics(topic)
        )

    def recommended_difficulty(topic: str) -> str | None:
        counts = difficulty_counts[topic]
        mastery = topic_mastery(topic)
        if mastery < 40:
            preferred = ["Easy", "Medium", "Hard"]
        elif mastery < ROADMAP_MASTERED:
            preferred = ["Medium", "Easy", "Hard"]
        else:
            preferred = ["Hard", "Medium", "Easy"]
        return next((level for level in preferred if counts[level] > 0), None)

    rows = []
    for topic in available_topics:
        stat = stats[topic]
        mastery = topic_mastery(topic)
        attempted = len(stat["problem_ids"])
        solved = len(stat["solved_problem_ids"])
        mastered = is_mastered(topic)
        prereqs = prerequisite_topics(topic)
        unmet = [item for item in prereqs if not is_mastered(item)]
        unlocked = not unmet
        tier = ROADMAP_TIER.get(topic, 2)
        status = "mastered" if mastered else ("available" if unlocked else "locked")

        if mastered:
            why = "Mastery evidence is established for this topic."
        elif unmet:
            why = "Complete the prerequisite topic(s) first: " + ", ".join(unmet) + "."
        elif tier < target_tier:
            why = (
                f"Foundation topic kept in the path before the {experience.lower()} "
                "starting tier."
            )
        elif attempted:
            why = "This topic is available and your current evidence shows room to improve."
        else:
            why = "This topic is available and ready to enter your current learning path."

        rows.append({
            "topic": topic,
            "status": status,
            "mastery": mastery,
            "attempted_problems": attempted,
            "solved_problems": solved,
            "available_problems": available_topic_counts[topic],
            "available_easy": difficulty_counts[topic]["Easy"],
            "available_medium": difficulty_counts[topic]["Medium"],
            "available_hard": difficulty_counts[topic]["Hard"],
            "recommended_difficulty": recommended_difficulty(topic),
            "acceptance_rate": round(
                stat["accepted"] / stat["submissions"] * 100
            ) if stat["submissions"] else 0,
            "tier": tier,
            "prerequisites": prereqs,
            "unmet_prerequisites": unmet,
            "unlocked": unlocked,
            "why": why,
        })

    # Choose the current focus from unlocked, non-mastered topics. The target
    # experience tier influences where we enter the graph, but prerequisites
    # always win, so an Advanced profile cannot silently skip foundations.
    candidates = [
        row for row in rows
        if row["unlocked"] and row["status"] != "mastered"
    ]
    candidates.sort(
        key=lambda row: (
            abs(row["tier"] - target_tier),
            row["mastery"],
            -row["available_problems"],
            row["topic"],
        )
    )
    current_topic = candidates[0]["topic"] if candidates else None

    roadmap = []
    for row in rows:
        if row["status"] == "mastered":
            position = "completed"
        elif row["topic"] == current_topic:
            position = "current"
        elif row["unlocked"]:
            position = "up_next"
        else:
            position = "locked"

        roadmap.append({
            **row,
            "position": position,
        })

    # Keep the UI focused: show completed milestones, the current focus, the
    # next few unlocked topics, and a small preview of locked prerequisites.
    completed = sorted(
        [row for row in roadmap if row["position"] == "completed"],
        key=lambda row: (-row["mastery"], row["topic"]),
    )[:3]
    current = [row for row in roadmap if row["position"] == "current"]
    up_next = sorted(
        [row for row in roadmap if row["position"] == "up_next"],
        key=lambda row: (
            abs(row["tier"] - target_tier),
            row["mastery"],
            row["topic"],
        ),
    )[:5]
    locked = sorted(
        [row for row in roadmap if row["position"] == "locked"],
        key=lambda row: (row["tier"], row["topic"]),
    )[:3]

    visible = completed[::-1] + current + up_next + locked

    return {
        "items": visible,
        "current_topic": current_topic,
        "available_topic_count": len(available_topics),
        "experience_level": experience,
        "target_tier": target_tier,
        "unlock_mastery": ROADMAP_MASTERY_UNLOCK,
        "unlock_evidence": ROADMAP_MIN_EVIDENCE,
        "mastery_threshold": ROADMAP_MASTERED,
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