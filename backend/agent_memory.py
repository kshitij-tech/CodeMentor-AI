from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.agent_models import LearningState
from backend.models import CodingAttempt, MentorMessage, MentorSession, Problem, User


MEMORY_SCOPE = "agent-memory"
AUDIT_SCOPE = "agent-audit"
MAX_MEMORY_CHARS = 10000


def _get_session(db: Session, user: User, scope: str) -> MentorSession:
    session = (
        db.query(MentorSession)
        .filter(
            MentorSession.user_id == user.id,
            MentorSession.scope == scope,
            MentorSession.problem_id.is_(None),
        )
        .order_by(MentorSession.updated_at.desc())
        .first()
    )
    if session is not None:
        return session
    session = MentorSession(
        user_id=user.id,
        problem_id=None,
        scope=scope,
        title="CodeMentor Agent Memory" if scope == MEMORY_SCOPE else "CodeMentor Agent Audit",
    )
    db.add(session)
    db.flush()
    return session


def load_memory(db: Session, user: User) -> dict[str, Any]:
    session = _get_session(db, user, MEMORY_SCOPE)
    message = (
        db.query(MentorMessage)
        .filter(
            MentorMessage.session_id == session.id,
            MentorMessage.role == "system",
            MentorMessage.action == "memory",
        )
        .order_by(MentorMessage.created_at.desc(), MentorMessage.id.desc())
        .first()
    )
    if message is None:
        return {}
    try:
        value = json.loads(message.content)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_memory(db: Session, user: User, memory: dict[str, Any]) -> None:
    session = _get_session(db, user, MEMORY_SCOPE)
    payload = json.dumps(memory, ensure_ascii=False, separators=(",", ":"))
    payload = payload[:MAX_MEMORY_CHARS]
    message = MentorMessage(
        session_id=session.id,
        role="system",
        content=payload,
        action="memory",
        hint_level=None,
    )
    db.add(message)
    session.updated_at = datetime.now(timezone.utc)
    db.commit()


def audit_tool_call(
    db: Session,
    user: User,
    event: dict[str, Any],
) -> None:
    session = _get_session(db, user, AUDIT_SCOPE)
    message = MentorMessage(
        session_id=session.id,
        role="system",
        content=json.dumps(event, ensure_ascii=False, separators=(",", ":"))[:4000],
        action="tool_call",
        hint_level=None,
    )
    db.add(message)
    session.updated_at = datetime.now(timezone.utc)
    db.commit()


def summarize_learning_state(db: Session, user: User) -> LearningState:
    rows = (
        db.query(CodingAttempt, Problem)
        .join(Problem, CodingAttempt.problem_id == Problem.id)
        .filter(CodingAttempt.user_id == user.id)
        .order_by(CodingAttempt.created_at.desc(), CodingAttempt.id.desc())
        .limit(80)
        .all()
    )

    state = LearningState(
        total_attempts=len(rows),
        total_submissions=sum(attempt.mode == "submit" for attempt, _ in rows),
        total_solved=len(
            {
                attempt.problem_id
                for attempt, _ in rows
                if attempt.mode == "submit" and attempt.status == "Accepted"
            }
        ),
        recent_activity=[],
    )

    topic_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"attempted": 0, "accepted": 0, "failures": 0}
    )
    mistake_counts: Counter[tuple[str, str]] = Counter()

    for attempt, problem in rows:
        topics = list(problem.topics or [])
        for topic in topics:
            stat = topic_stats[topic]
            stat["attempted"] += 1
            if attempt.mode == "submit" and attempt.status == "Accepted":
                stat["accepted"] += 1
            elif attempt.mode == "submit":
                stat["failures"] += 1
                mistake_counts[(topic, attempt.status)] += 1

    focus = []
    for topic, stat in topic_stats.items():
        attempted = stat["attempted"]
        acceptance = stat["accepted"] / max(attempted, 1)
        mastery = round(
            (0.70 * (stat["accepted"] / max(attempted, 1))
             + 0.30 * (stat["accepted"] / max(
                 sum(
                     1
                     for attempt, problem in rows
                     if attempt.mode == "submit" and topic in (problem.topics or [])
                 ),
                 1,
             ))) * min(1.0, attempted / 10.0) * 100
        )
        focus.append(
            {
                "topic": topic,
                "mastery": mastery,
                "attempted_problems": attempted,
                "acceptance_rate": round(acceptance * 100),
            }
        )

    focus.sort(key=lambda item: (item["mastery"], -item["attempted_problems"], item["topic"]))
    state.focus_topics = focus[:8]

    recurring = []
    for (topic, status), count in mistake_counts.most_common():
        if count < 2:
            continue
        recurring.append(
            {
                "topic": topic,
                "pattern": status,
                "occurrences": count,
            }
        )
    state.recurring_mistakes = recurring[:8]

    # Repeated low-acceptance outcomes are treated as conceptual risks rather
    # than diagnoses. The agent must present them as hypotheses to validate.
    risks = []
    for item in focus:
        if item["attempted_problems"] >= 3 and item["acceptance_rate"] < 50:
            risks.append(
                {
                    "topic": item["topic"],
                    "signal": "low_acceptance",
                    "confidence": min(0.95, 0.45 + item["attempted_problems"] / 20),
                    "hypothesis": "The learner may need a clearer mental model or stronger edge-case reasoning in this topic.",
                }
            )
    state.conceptual_risks = risks[:6]

    objectives = []
    for item in focus[:5]:
        if item["mastery"] < 75:
            objectives.append({
                "topic": item["topic"],
                "target_mastery": 75,
                "current_mastery": item["mastery"],
                "next_action": "Practice one targeted problem and explain the key invariant before coding.",
            })
    for mistake in state.recurring_mistakes[:3]:
        objectives.append({
            "topic": mistake["topic"],
            "target": f"Reduce repeated {mistake['pattern']} outcomes",
            "next_action": "Review the latest failure and write the reason for the failure before attempting another solution.",
        })
    state.learning_objectives = objectives[:8]

    for attempt, problem in rows[:10]:
        state.recent_activity.append(
            {
                "problem": problem.title,
                "topic": (problem.topics or [None])[0],
                "status": attempt.status,
                "mode": attempt.mode,
            }
        )

    return state


def memory_snapshot(state: LearningState) -> dict[str, Any]:
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "focus_topics": state.focus_topics,
        "recurring_mistakes": state.recurring_mistakes,
        "conceptual_risks": state.conceptual_risks,
        "learning_objectives": state.learning_objectives,
        "recent_activity": state.recent_activity,
    }
