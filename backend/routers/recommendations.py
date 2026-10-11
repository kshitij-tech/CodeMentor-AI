from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import CodingAttempt, Problem, User, UserProfile
from backend.problem_catalog import canonicalize_topics
from backend.routers.auth import get_current_user
from backend.routers.problems import _catalog_rows
from roadmap.adaptive_learning import (
    build_learning_state,
    build_roadmap,
    explain_recommendation,
    mastered_topics,
    recommend_problem,
    skills_payload,
    weak_topics,
)

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


def _attempts(db: Session, user_id: int) -> list[CodingAttempt]:
    return (
        db.query(CodingAttempt)
        .filter(CodingAttempt.user_id == user_id)
        .order_by(CodingAttempt.created_at.asc(), CodingAttempt.id.asc())
        .all()
    )


def _catalog(db: Session) -> list[dict[str, Any]]:
    # The Practice catalogue is the single source of truth for normalized,
    # English-only problems and canonical topic names.
    return _catalog_rows(db)


def _profile_experience(db: Session, user_id: int) -> str:
    profile = (
        db.query(UserProfile)
        .filter(UserProfile.user_id == user_id)
        .first()
    )
    return (profile.experience_level if profile else None) or "Beginner"


def _problem_payload(problem: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(problem["id"]),
        "slug": problem.get("slug"),
        "title": problem.get("title"),
        "difficulty": problem.get("difficulty"),
        "topics": canonicalize_topics(problem.get("topics")),
    }


def _build_state(
    db: Session,
    current_user: User,
    catalog: Iterable[dict[str, Any]],
):
    return build_learning_state(
        catalog,
        _attempts(db, current_user.id),
    )


@router.get("/skills")
def learning_skills(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return confidence-aware topic/difficulty skill telemetry for visualizations."""
    catalog = _catalog(db)
    state = _build_state(db, current_user, catalog)
    return skills_payload(
        state,
        experience_level=_profile_experience(db, current_user.id),
    )


@router.get("/next")
def next_recommendation(
    current_problem_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the next deterministic adaptive problem."""
    catalog = _catalog(db)
    state = _build_state(db, current_user, catalog)
    experience = _profile_experience(db, current_user.id)
    catalog_by_id = {int(row["id"]): row for row in catalog}

    # Preserve the active-learning UX: an unsolved active problem stays in
    # place until it is accepted, while the adaptive engine plans what follows.
    if current_problem_id is not None:
        current = catalog_by_id.get(int(current_problem_id))
        if current is not None and int(current_problem_id) not in state.solved_ids:
            explanation = explain_recommendation(
                current,
                state,
                experience_level=experience,
                candidate_count=len(catalog_by_id),
            )
            focus_topic = (current.get("topics") or [None])[0]
            topic_metrics = [
                state.topics.get(topic)
                for topic in current.get("topics") or []
                if state.topics.get(topic) is not None
            ]
            if topic_metrics:
                focus_topic = min(topic_metrics, key=lambda metric: metric.mastery).key
            topic_health = (
                round(
                    min(
                        metric.mastery
                        for metric in topic_metrics
                    ) / 100.0,
                    3,
                )
                if topic_metrics
                else None
            )
            return {
                "problem": _problem_payload(current),
                "reason": (
                    "Keep working on this problem. A new recommendation will "
                    "appear after you solve it."
                ),
                "focus_topic": focus_topic,
                "score": explanation["score_breakdown"].get("score"),
                "topic_health": topic_health,
                "is_reinforcement": bool(explanation["was_attempted"]),
                "locked_until_solved": True,
                "profile_experience": experience,
                "adaptive_difficulty": explanation["score_breakdown"].get("difficulty_policy"),
                "explanation": explanation,
            }

    problem, breakdown = recommend_problem(
        catalog,
        state,
        experience_level=experience,
    )
    if problem is None:
        return {
            "problem": None,
            "reason": "You have solved every currently eligible problem.",
            "focus_topic": None,
            "score": None,
            "topic_health": None,
            "is_reinforcement": False,
            "locked_until_solved": False,
            "profile_experience": experience,
            "adaptive_difficulty": (
                breakdown["difficulty_policy"] if breakdown else None
            ),
        }

    explanation = explain_recommendation(
        problem,
        state,
        experience_level=experience,
        candidate_count=max(1, len(catalog)),
    )
    topics = list(problem.get("topics") or [])
    metrics = [
        state.topics[topic]
        for topic in topics
        if topic in state.topics
    ]
    focus_metric = min(
        metrics,
        key=lambda metric: metric.mastery,
        default=None,
    )

    return {
        "problem": _problem_payload(problem),
        "reason": explanation["why"],
        "focus_topic": focus_metric.key if focus_metric else (topics[0] if topics else None),
        "score": breakdown.get("score") if breakdown else None,
        "topic_health": (
            round(focus_metric.mastery / 100.0, 3)
            if focus_metric
            else None
        ),
        "is_reinforcement": bool(
            breakdown and breakdown.get("recent_mistake_signal", 0) > 0
        ),
        "locked_until_solved": False,
        "profile_experience": experience,
        "adaptive_difficulty": (
            breakdown.get("difficulty_policy") if breakdown else None
        ),
        "explanation": explanation,
    }


@router.get("/why/{problem_id}")
def why_problem(
    problem_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explain the adaptive score for one problem using the same policy as /next."""
    catalog = _catalog(db)
    catalog_by_id = {int(row["id"]): row for row in catalog}
    problem = catalog_by_id.get(problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found.")

    state = _build_state(db, current_user, catalog)
    experience = _profile_experience(db, current_user.id)
    explanation = explain_recommendation(
        problem,
        state,
        experience_level=experience,
        candidate_count=max(1, len(catalog)),
    )
    return {
        **explanation,
        "problem": _problem_payload(problem),
    }


@router.get("/roadmap")
def learning_roadmap(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Build the personalized prerequisite roadmap from the real catalogue."""
    catalog = _catalog(db)
    state = _build_state(db, current_user, catalog)
    return build_roadmap(
        catalog,
        state,
        experience_level=_profile_experience(db, current_user.id),
    )


@router.get("/weak")
def weak_topic_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return evidence-backed weak topics with gaps and recent mistake pressure."""
    catalog = _catalog(db)
    state = _build_state(db, current_user, catalog)
    items = []
    for metric in weak_topics(state, limit=5):
        items.append({
            "topic": metric.key,
            "skill_score": metric.skill_score,
            "mastery": metric.mastery,
            "confidence": metric.confidence,
            "gap": metric.gap,
            "attempted_problems": metric.attempted_problems,
            "solved_problems": metric.solved_problems,
            "submissions": metric.submissions,
            "accepted_submissions": metric.submissions - metric.failures,
            "failures": metric.failures,
            "recent_failures": metric.recent_failures,
            "acceptance_rate": metric.acceptance_rate,
            "status": metric.status,
        })
    return {
        "items": items,
        "mastered_topics": [metric.key for metric in mastered_topics(state)],
    }


@router.get("/mastered")
def mastered_topic_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return topics that have crossed the mastery and evidence thresholds."""
    catalog = _catalog(db)
    state = _build_state(db, current_user, catalog)
    return {
        "items": [
            {
                "topic": metric.key,
                "skill_score": metric.skill_score,
                "mastery": metric.mastery,
                "confidence": metric.confidence,
                "attempted_problems": metric.attempted_problems,
                "solved_problems": metric.solved_problems,
                "acceptance_rate": metric.acceptance_rate,
                "status": metric.status,
            }
            for metric in mastered_topics(state)
        ]
    }
