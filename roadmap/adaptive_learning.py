"""Deterministic adaptive-learning engine for DSA skill estimation and recommendations.

The module deliberately contains no FastAPI or SQLAlchemy dependencies. The router
translates database rows into plain Python dictionaries and delegates the learning
logic here. This makes the recommendation policy deterministic and independently
testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import exp, sqrt
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

DIFFICULTIES: tuple[str, ...] = ("Easy", "Medium", "Hard")
DIFFICULTY_RANK: dict[str, int] = {"Easy": 0, "Medium": 1, "Hard": 2}

PREREQUISITE_GRAPH: dict[str, tuple[str, ...]] = {
    "Arrays & Strings": (),
    "Hashing & Hash Maps": ("Arrays & Strings",),
    "Sorting": ("Arrays & Strings",),
    "Prefix Sum": ("Arrays & Strings",),
    "Two Pointers": ("Arrays & Strings", "Sorting"),
    "Sliding Window": ("Arrays & Strings", "Two Pointers"),
    "Binary Search": ("Arrays & Strings", "Sorting"),
    "Stacks & Queues": ("Arrays & Strings",),
    "Linked Lists": ("Arrays & Strings",),
    "Intervals": ("Arrays & Strings", "Sorting"),
    "Trees & BST": ("Stacks & Queues",),
    "Heaps & Priority Queues": ("Trees & BST",),
    "Backtracking": ("Trees & BST",),
    "Greedy Algorithms": ("Sorting", "Prefix Sum"),
    "Bit Manipulation": ("Arrays & Strings",),
    "Graphs (BFS/DFS)": ("Trees & BST",),
    "Dynamic Programming": ("Arrays & Strings", "Prefix Sum"),
    "Math": ("Arrays & Strings",),
}

TOPIC_DEPENDENCY_GRAPH: dict[str, tuple[str, ...]] = {
    topic: tuple(
        dependent
        for dependent, prerequisites in PREREQUISITE_GRAPH.items()
        if topic in prerequisites
    )
    for topic in PREREQUISITE_GRAPH
}

ROADMAP_TIER: dict[str, int] = {
    "Arrays & Strings": 1,
    "Hashing & Hash Maps": 1,
    "Sorting": 1,
    "Prefix Sum": 1,
    "Math": 1,
    "Two Pointers": 2,
    "Sliding Window": 2,
    "Binary Search": 2,
    "Stacks & Queues": 2,
    "Linked Lists": 2,
    "Intervals": 2,
    "Bit Manipulation": 2,
    "Trees & BST": 3,
    "Heaps & Priority Queues": 3,
    "Backtracking": 3,
    "Greedy Algorithms": 3,
    "Graphs (BFS/DFS)": 4,
    "Dynamic Programming": 4,
}

OUTCOME_SIGNAL: dict[str, float] = {
    "accepted": 1.0,
    "wrong answer": 0.0,
    "time limit exceeded": 0.10,
    "runtime error": 0.15,
    "compile error": 0.20,
    "rejected": 0.05,
    "unsupported problem format": 0.05,
    "judge error": 0.20,
    "output limit exceeded": 0.10,
}
SUBMISSION_MODES = {"submit"}
MODE_WEIGHT = {"submit": 1.0, "run": 0.25}

RECENCY_HALF_LIFE_DAYS = 30.0
RECENT_MISTAKE_WINDOW_DAYS = 14
RECENT_BALANCE_WINDOW_DAYS = 30

MASTERED_MASTERY = 75.0
MASTERED_CONFIDENCE = 60.0
MASTERED_MIN_DISTINCT = 3
PREREQUISITE_MASTERY = 65.0
PREREQUISITE_CONFIDENCE = 55.0

STATUS_MASTERED = "mastered"
STATUS_WEAK = "weak"
STATUS_DEVELOPING = "developing"
STATUS_UNPRACTICED = "unpracticed"


@dataclass(frozen=True)
class AttemptEvidence:
    problem_id: int
    topic: str
    difficulty: str
    mode: str
    status: str
    created_at: datetime
    signal: float
    recency_weight: float
    effective_weight: float


@dataclass
class ProblemHistory:
    problem_id: int
    difficulty: str
    topics: tuple[str, ...]
    evidence: list[AttemptEvidence]

    @property
    def submissions(self) -> list[AttemptEvidence]:
        return [item for item in self.evidence if item.mode in SUBMISSION_MODES]

    @property
    def solved(self) -> bool:
        return any(
            item.mode in SUBMISSION_MODES and item.status.lower() == "accepted"
            for item in self.evidence
        )

    @property
    def last_attempt_at(self) -> datetime | None:
        return max((item.created_at for item in self.evidence), default=None)

    @property
    def last_submit_at(self) -> datetime | None:
        return max((item.created_at for item in self.submissions), default=None)

    @property
    def last_status(self) -> str | None:
        latest = max(self.evidence, key=lambda item: item.created_at, default=None)
        return latest.status if latest else None

    @property
    def weighted_score(self) -> float:
        items = self.submissions
        if not items:
            return 0.0
        numerator = sum(item.signal * item.effective_weight for item in items)
        denominator = sum(item.effective_weight for item in items)
        return numerator / denominator if denominator else 0.0


@dataclass(frozen=True)
class SkillMetric:
    key: str
    skill_score: float
    mastery: float
    confidence: float
    gap: float
    attempted_problems: int
    solved_problems: int
    submissions: int
    failures: int
    recent_failures: float
    recent_attempts: int
    acceptance_rate: float
    last_attempt_at: datetime | None
    status: str


@dataclass(frozen=True)
class LearningState:
    topics: dict[str, SkillMetric]
    difficulties: dict[str, SkillMetric]
    problem_history: dict[int, ProblemHistory]
    solved_ids: frozenset[int]
    attempted_ids: frozenset[int]
    recent_topic_attempts: dict[str, float]
    recent_topic_failures: dict[str, float]
    now: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalise_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _difficulty(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    aliases = {
        "easy": "Easy",
        "beginner": "Easy",
        "medium": "Medium",
        "intermediate": "Medium",
        "hard": "Hard",
        "advanced": "Hard",
    }
    return aliases.get(text)


def _recency_weight(created_at: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def _signal(status: str) -> float:
    key = _normalise_key(status)
    return OUTCOME_SIGNAL.get(key, 0.05)


def _attempt_weight(
    *,
    mode: str,
    recency_weight: float,
    ordinal_for_problem: int,
) -> float:
    repeat_decay = 1.0 / sqrt(max(1, ordinal_for_problem))
    return MODE_WEIGHT.get(_normalise_key(mode), 0.10) * recency_weight * repeat_decay


def _weighted_mean(values: Iterable[tuple[float, float]]) -> float:
    pairs = [(float(value), max(0.0, float(weight))) for value, weight in values]
    pairs = [(value, weight) for value, weight in pairs if weight > 0]
    if not pairs:
        return 0.0
    return sum(value * weight for value, weight in pairs) / sum(weight for _, weight in pairs)


def _consistency(signals: Sequence[float]) -> float:
    if not signals:
        return 0.0
    center = mean(signals)
    dispersion = mean(abs(value - center) for value in signals)
    return max(0.0, min(1.0, 1.0 - 2.0 * dispersion))


def _confidence(
    distinct_problems: int,
    submissions: int,
    signals: Sequence[float],
) -> float:
    if distinct_problems <= 0 or submissions <= 0:
        return 0.0
    distinct_factor = min(1.0, distinct_problems / 5.0)
    attempt_factor = min(1.0, submissions / 8.0)
    consistency = _consistency(signals)
    score = 0.50 * distinct_factor + 0.30 * attempt_factor + 0.20 * consistency
    return max(0.0, min(1.0, score))


def _metric(
    *,
    key: str,
    problem_histories: Sequence[ProblemHistory],
    now: datetime,
) -> SkillMetric:
    distinct = len(problem_histories)
    submission_evidence = [
        item
        for history in problem_histories
        for item in history.submissions
    ]
    solved = sum(1 for history in problem_histories if history.solved)
    signals = [item.signal for item in submission_evidence]

    weighted_problem_scores: list[tuple[float, float]] = []
    for history in problem_histories:
        if not history.submissions:
            continue
        recency = _recency_weight(history.last_submit_at or now, now)
        weighted_problem_scores.append(
            (history.weighted_score, 0.35 + 0.65 * recency)
        )

    skill_score = _weighted_mean(weighted_problem_scores) * 100.0
    conf = _confidence(distinct, len(submission_evidence), signals) * 100.0
    mastery = skill_score * (conf / 100.0)

    attempts = sum(len(history.evidence) for history in problem_histories)
    recent_attempts = sum(
        1
        for history in problem_histories
        for item in history.evidence
        if item.created_at >= now - timedelta(days=RECENT_BALANCE_WINDOW_DAYS)
    )
    accepted = sum(
        1
        for item in submission_evidence
        if item.status.lower() == "accepted"
    )
    failures = len(submission_evidence) - accepted
    acceptance_rate = (
        accepted / len(submission_evidence) * 100.0
        if submission_evidence
        else 0.0
    )
    last_attempt = max(
        (item.created_at for history in problem_histories for item in history.evidence),
        default=None,
    )

    if distinct == 0:
        status = STATUS_UNPRACTICED
    elif mastery >= MASTERED_MASTERY and conf >= MASTERED_CONFIDENCE:
        status = STATUS_MASTERED
    elif mastery < 45:
        status = STATUS_WEAK
    else:
        status = STATUS_DEVELOPING

    return SkillMetric(
        key=key,
        skill_score=round(skill_score, 2),
        mastery=round(mastery, 2),
        confidence=round(conf, 2),
        gap=round(max(0.0, 100.0 - mastery), 2),
        attempted_problems=distinct,
        solved_problems=solved,
        submissions=len(submission_evidence),
        failures=failures,
        recent_failures=round(
            sum(
                item.effective_weight
                for item in submission_evidence
                if item.status.lower() != "accepted"
                and item.created_at >= now - timedelta(days=RECENT_MISTAKE_WINDOW_DAYS)
            ),
            3,
        ),
        recent_attempts=recent_attempts,
        acceptance_rate=round(acceptance_rate, 2),
        last_attempt_at=last_attempt,
        status=status,
    )


def _catalog_map(catalog: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in catalog:
        try:
            problem_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        difficulty = _difficulty(row.get("difficulty"))
        topics = tuple(
            dict.fromkeys(
                str(topic).strip()
                for topic in (row.get("topics") or [])
                if str(topic).strip()
            )
        )
        if problem_id <= 0 or difficulty is None:
            continue
        result[problem_id] = {
            "id": problem_id,
            "slug": row.get("slug"),
            "title": row.get("title"),
            "difficulty": difficulty,
            "topics": topics,
        }
    return result


def build_learning_state(
    catalog: Iterable[Mapping[str, Any]],
    attempts: Iterable[Any],
    *,
    now: datetime | None = None,
) -> LearningState:
    """Build all learner telemetry needed by roadmap and recommendation endpoints.

    attempts may contain CodingAttempt ORM objects or any object exposing the
    same attributes. Invalid or non-catalogue attempts are ignored.
    """
    current_time = _as_utc(now, _utc_now())
    catalogue = _catalog_map(catalog)
    histories: dict[int, ProblemHistory] = {
        problem_id: ProblemHistory(
            problem_id=problem_id,
            difficulty=row["difficulty"],
            topics=tuple(row["topics"]),
            evidence=[],
        )
        for problem_id, row in catalogue.items()
    }
    ordered = sorted(
        (
            attempt
            for attempt in attempts
            if getattr(attempt, "problem_id", None) in histories
            and getattr(attempt, "created_at", None) is not None
        ),
        key=lambda item: (
            _as_utc(getattr(item, "created_at", None), current_time),
            int(getattr(item, "id", 0) or 0),
        ),
    )

    problem_ordinals: dict[int, int] = {}
    recent_topic_attempts: dict[str, float] = {}
    recent_topic_failures: dict[str, float] = {}

    for attempt in ordered:
        problem_id = int(getattr(attempt, "problem_id"))
        created_at = _as_utc(getattr(attempt, "created_at", None), current_time)
        history = histories[problem_id]
        problem_ordinals[problem_id] = problem_ordinals.get(problem_id, 0) + 1
        mode = _normalise_key(getattr(attempt, "mode", ""))
        status = str(getattr(attempt, "status", "") or "Unknown").strip()
        recency = _recency_weight(created_at, current_time)
        evidence = AttemptEvidence(
            problem_id=problem_id,
            topic=history.topics[0] if history.topics else "",
            difficulty=history.difficulty,
            mode=mode,
            status=status,
            created_at=created_at,
            signal=_signal(status),
            recency_weight=recency,
            effective_weight=_attempt_weight(
                mode=mode,
                recency_weight=recency,
                ordinal_for_problem=problem_ordinals[problem_id],
            ),
        )
        history.evidence.append(evidence)

        if created_at >= current_time - timedelta(days=RECENT_BALANCE_WINDOW_DAYS):
            for topic in history.topics:
                recent_topic_attempts[topic] = recent_topic_attempts.get(topic, 0.0) + 1.0
        if (
            mode in SUBMISSION_MODES
            and _normalise_key(status) != "accepted"
            and created_at >= current_time - timedelta(days=RECENT_MISTAKE_WINDOW_DAYS)
        ):
            for topic in history.topics:
                recent_topic_failures[topic] = (
                    recent_topic_failures.get(topic, 0.0) + recency
                )

    topic_histories: dict[str, list[ProblemHistory]] = {}
    difficulty_histories: dict[str, list[ProblemHistory]] = {
        difficulty: [] for difficulty in DIFFICULTIES
    }
    for history in histories.values():
        if not history.evidence:
            continue
        difficulty_histories[history.difficulty].append(history)
        for topic in history.topics:
            topic_histories.setdefault(topic, []).append(history)

    topic_metrics = {
        topic: _metric(
            key=topic,
            problem_histories=topic_histories.get(topic, []),
            now=current_time,
        )
        for topic in PREREQUISITE_GRAPH
    }
    difficulty_metrics = {
        difficulty: _metric(
            key=difficulty,
            problem_histories=difficulty_histories[difficulty],
            now=current_time,
        )
        for difficulty in DIFFICULTIES
    }

    solved_ids = frozenset(
        problem_id
        for problem_id, history in histories.items()
        if history.solved
    )
    attempted_ids = frozenset(
        problem_id
        for problem_id, history in histories.items()
        if history.evidence
    )

    return LearningState(
        topics=topic_metrics,
        difficulties=difficulty_metrics,
        problem_history=histories,
        solved_ids=solved_ids,
        attempted_ids=attempted_ids,
        recent_topic_attempts=recent_topic_attempts,
        recent_topic_failures=recent_topic_failures,
        now=current_time,
    )


def _topic_mastered(metric: SkillMetric | None) -> bool:
    return bool(
        metric
        and metric.mastery >= MASTERED_MASTERY
        and metric.confidence >= MASTERED_CONFIDENCE
        and metric.attempted_problems >= MASTERED_MIN_DISTINCT
    )


def weak_topics(state: LearningState, limit: int = 5) -> list[SkillMetric]:
    metrics = list(state.topics.values())
    metrics.sort(
        key=lambda item: (
            -item.gap,
            item.confidence,
            item.attempted_problems,
            item.key,
        )
    )
    return metrics[: max(0, limit)]


def mastered_topics(state: LearningState) -> list[SkillMetric]:
    return sorted(
        (
            metric
            for metric in state.topics.values()
            if _topic_mastered(metric)
        ),
        key=lambda item: (-item.mastery, -item.confidence, item.key),
    )


def _available_prerequisites(
    topic: str,
    available_topics: set[str],
) -> tuple[str, ...]:
    return tuple(
        prerequisite
        for prerequisite in PREREQUISITE_GRAPH.get(topic, ())
        if prerequisite in available_topics
    )


def prerequisites_for_problem(
    problem: Mapping[str, Any],
    available_topics: set[str],
) -> tuple[str, ...]:
    prerequisites: set[str] = set()
    for topic in problem.get("topics") or ():
        prerequisites.update(
            _available_prerequisites(str(topic), available_topics)
        )
    return tuple(sorted(prerequisites))


def prerequisites_met(
    problem: Mapping[str, Any],
    state: LearningState,
    available_topics: set[str] | None = None,
) -> tuple[bool, list[str]]:
    topics = available_topics or set(state.topics)
    unmet = [
        prerequisite
        for prerequisite in prerequisites_for_problem(problem, topics)
        if not _topic_mastered(state.topics.get(prerequisite))
    ]
    return not unmet, unmet


def _global_mastery(state: LearningState) -> float:
    evidenced = [
        metric for metric in state.topics.values()
        if metric.attempted_problems > 0
    ]
    if not evidenced:
        return 0.0
    return _weighted_mean(
        (metric.mastery, max(1.0, metric.attempted_problems))
        for metric in evidenced
    )


def adaptive_difficulty(
    state: LearningState,
    *,
    experience_level: str | None = None,
) -> dict[str, Any]:
    """Return the highest evidence-supported difficulty to target next."""
    experience = str(experience_level or "Beginner").strip().title()
    easy = state.difficulties["Easy"]
    medium = state.difficulties["Medium"]

    medium_ready = (
        (
            easy.mastery >= 55.0
            and easy.confidence >= 45.0
            and easy.acceptance_rate >= 55.0
        )
        or (
            experience in {"Intermediate", "Advanced"}
            and not state.attempted_ids
        )
    )
    hard_ready = (
        medium.mastery >= 70.0
        and medium.confidence >= 60.0
        and medium.acceptance_rate >= 65.0
        and medium.attempted_problems >= 4
        and medium.recent_failures < 2.0
    )

    if hard_ready:
        target = "Hard"
    elif medium_ready:
        target = "Medium"
    else:
        target = "Easy"

    return {
        "target": target,
        "medium_ready": medium_ready,
        "hard_ready": hard_ready,
        "global_mastery": round(_global_mastery(state), 2),
        "reason": (
            "Hard unlocked by strong, consistent Medium evidence."
            if hard_ready
            else "Hard remains locked until Medium mastery, confidence, evidence, and acceptance thresholds are met."
            if target != "Hard"
            else "Medium is the current adaptive target."
        ),
    }


def _topic_need(
    problem: Mapping[str, Any],
    state: LearningState,
) -> float:
    metrics = [
        state.topics.get(str(topic))
        for topic in (problem.get("topics") or ())
        if state.topics.get(str(topic)) is not None
    ]
    if not metrics:
        return 0.25
    gap = mean(metric.gap for metric in metrics) / 100.0
    failures = mean(
        min(1.0, metric.recent_failures / 2.5)
        for metric in metrics
    )
    unpracticed = mean(
        1.0 if metric.status == STATUS_UNPRACTICED else 0.0
        for metric in metrics
    )
    return max(0.0, min(1.0, 0.70 * gap + 0.20 * failures + 0.10 * unpracticed))


def _difficulty_fit(
    difficulty: str,
    target: str,
    *,
    hard_ready: bool,
) -> tuple[float, bool]:
    if difficulty == "Hard" and not hard_ready:
        return 0.0, False
    distance = abs(DIFFICULTY_RANK[difficulty] - DIFFICULTY_RANK[target])
    if distance == 0:
        return 1.0, True
    if distance == 1:
        if DIFFICULTY_RANK[difficulty] < DIFFICULTY_RANK[target]:
            return 0.72, True
        return 0.18, True
    return 0.0, False


def _topic_balance(
    problem: Mapping[str, Any],
    state: LearningState,
    *,
    candidate_count: int,
) -> float:
    topics = [str(topic) for topic in (problem.get("topics") or ())]
    if not topics:
        return 0.0
    recent_counts = [
        state.recent_topic_attempts.get(topic, 0.0)
        for topic in topics
    ]
    minimum = max(0.0, min(recent_counts) if recent_counts else 0.0)
    scale = max(1.0, float(candidate_count))
    return max(0.0, min(1.0, 1.0 - minimum / (minimum + scale)))


def _recent_repetition(
    history: ProblemHistory,
    now: datetime,
) -> float:
    if not history.evidence:
        return 0.0
    if history.last_attempt_at is None:
        return 0.0
    days = max(
        0.0,
        (now - history.last_attempt_at).total_seconds() / 86400.0,
    )
    if days < 3:
        return 1.0
    if days < 7:
        return 0.60
    if days < 30:
        return 0.25
    return 0.0


def _candidate_breakdown(
    problem: Mapping[str, Any],
    state: LearningState,
    *,
    experience_level: str | None,
    available_topics: set[str],
    candidate_count: int,
) -> dict[str, Any]:
    policy = adaptive_difficulty(state, experience_level=experience_level)
    prerequisites_ok, unmet = prerequisites_met(
        problem,
        state,
        available_topics,
    )
    target_difficulty = policy["target"]
    difficulty = str(problem["difficulty"])
    difficulty_fit, difficulty_allowed = _difficulty_fit(
        difficulty,
        target_difficulty,
        hard_ready=bool(policy["hard_ready"]),
    )
    history = state.problem_history[int(problem["id"])]
    topic_need = _topic_need(problem, state)
    topic_balance = _topic_balance(
        problem,
        state,
        candidate_count=candidate_count,
    )
    repetition = _recent_repetition(history, state.now)
    unattempted_bonus = 1.0 if not history.evidence else 0.0
    recent_failure = (
        mean(
            min(
                1.0,
                state.recent_topic_failures.get(str(topic), 0.0) / 2.5,
            )
            for topic in (problem.get("topics") or ())
        )
        if problem.get("topics")
        else 0.0
    )
    all_mastered = bool(problem.get("topics")) and all(
        _topic_mastered(state.topics.get(str(topic)))
        for topic in problem.get("topics") or ()
    )

    score = (
        4.20 * topic_need
        + 2.20 * difficulty_fit
        + 1.10 * recent_failure
        + 0.70 * topic_balance
        + 0.45 * unattempted_bonus
        - 1.20 * repetition
        - (0.80 if all_mastered else 0.0)
    )
    if not prerequisites_ok or not difficulty_allowed:
        score = float("-inf")

    return {
        "score": round(score, 6) if score != float("-inf") else None,
        "skill_gap": round(topic_need, 4),
        "prerequisites_met": prerequisites_ok,
        "unmet_prerequisites": unmet,
        "difficulty_target": target_difficulty,
        "difficulty_fit": round(difficulty_fit, 4),
        "hard_unlocked": bool(policy["hard_ready"]),
        "recent_mistake_signal": round(recent_failure, 4),
        "topic_balance": round(topic_balance, 4),
        "repetition_penalty": round(repetition, 4),
        "unattempted_bonus": round(unattempted_bonus, 4),
        "all_topics_mastered": all_mastered,
        "difficulty_policy": policy,
    }


def recommend_problem(
    catalog: Iterable[Mapping[str, Any]],
    state: LearningState,
    *,
    experience_level: str | None = None,
    excluded_ids: Iterable[int] = (),
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Select one deterministic next problem and return its scoring breakdown."""
    catalogue = _catalog_map(catalog)
    available_topics = set(state.topics)
    excluded = {int(problem_id) for problem_id in excluded_ids}

    candidates: list[tuple[float, int, dict[str, Any], dict[str, Any]]] = []
    for problem_id, problem in catalogue.items():
        if problem_id in state.solved_ids or problem_id in excluded:
            continue
        breakdown = _candidate_breakdown(
            problem,
            state,
            experience_level=experience_level,
            available_topics=available_topics,
            candidate_count=max(1, len(catalogue)),
        )
        if breakdown["score"] is None:
            continue
        candidates.append(
            (
                float(breakdown["score"]),
                problem_id,
                problem,
                breakdown,
            )
        )

    if not candidates:
        return None, {
            "eligible_count": 0,
            "difficulty_policy": adaptive_difficulty(
                state,
                experience_level=experience_level,
            ),
        }

    candidates.sort(key=lambda item: (-item[0], item[1]))
    _, _, problem, breakdown = candidates[0]
    return problem, {
        **breakdown,
        "eligible_count": len(candidates),
    }


def explain_recommendation(
    problem: Mapping[str, Any],
    state: LearningState,
    *,
    experience_level: str | None = None,
    candidate_count: int | None = None,
) -> dict[str, Any]:
    """Explain the same scoring calculation used for next-problem selection."""
    available_topics = set(state.topics)
    breakdown = _candidate_breakdown(
        problem,
        state,
        experience_level=experience_level,
        available_topics=available_topics,
        candidate_count=candidate_count or max(1, len(state.problem_history)),
    )
    problem_id = int(problem["id"])
    history = state.problem_history.get(problem_id)
    return {
        "problem_id": problem_id,
        "is_solved": bool(history and history.solved),
        "was_attempted": bool(history and history.evidence),
        "last_status": history.last_status if history else None,
        "attempt_count": len(history.evidence) if history else 0,
        "solved_history_rule": (
            "Solved problems are excluded from next-problem selection."
            if history and history.solved
            else "Unsolved problems remain eligible after prerequisite and difficulty checks."
        ),
        "score_breakdown": breakdown,
        "why": _build_reason(problem, breakdown, state),
    }


def _build_reason(
    problem: Mapping[str, Any],
    breakdown: Mapping[str, Any],
    state: LearningState,
) -> str:
    topics = [str(topic) for topic in (problem.get("topics") or ())]
    fallback_metric = SkillMetric(
        key="DSA",
        skill_score=0,
        mastery=0,
        confidence=0,
        gap=100,
        attempted_problems=0,
        solved_problems=0,
        submissions=0,
        failures=0,
        recent_failures=0,
        recent_attempts=0,
        acceptance_rate=0,
        last_attempt_at=None,
        status=STATUS_UNPRACTICED,
    )
    primary_topic = max(
        topics,
        key=lambda topic: state.topics.get(topic, fallback_metric).gap,
        default="DSA",
    )
    topic_metric = state.topics.get(primary_topic)
    topic_text = (
        f"{primary_topic} is at {topic_metric.mastery:.0f}% estimated mastery "
        f"with {topic_metric.confidence:.0f}% confidence"
        if topic_metric
        else f"{primary_topic} needs practice"
    )
    detail: list[str] = [topic_text]
    if breakdown.get("recent_mistake_signal", 0) > 0:
        detail.append("recent failed submissions increased its reinforcement priority")
    if breakdown.get("difficulty_target"):
        detail.append(
            f"the adaptive difficulty target is {breakdown['difficulty_target']}"
        )
    if breakdown.get("unattempted_bonus"):
        detail.append("the problem is new to you")
    elif breakdown.get("repetition_penalty", 0) > 0:
        detail.append("recent repetition is penalized")
    if breakdown.get("unmet_prerequisites"):
        detail.append(
            "prerequisites are still missing: "
            + ", ".join(breakdown["unmet_prerequisites"])
        )
    return "Recommended because " + "; ".join(detail) + "."


def build_roadmap(
    catalog: Iterable[Mapping[str, Any]],
    state: LearningState,
    *,
    experience_level: str | None = None,
    limit_completed: int = 3,
    limit_up_next: int = 5,
    limit_locked: int = 4,
) -> dict[str, Any]:
    """Build a personalized, prerequisite-aware roadmap."""
    catalogue = _catalog_map(catalog)
    available_topic_counts: dict[str, int] = {
        topic: 0 for topic in PREREQUISITE_GRAPH
    }
    difficulty_counts: dict[str, dict[str, int]] = {
        topic: {difficulty: 0 for difficulty in DIFFICULTIES}
        for topic in PREREQUISITE_GRAPH
    }
    available_topics: set[str] = set()
    for problem in catalogue.values():
        for topic in problem["topics"]:
            if topic not in available_topic_counts:
                continue
            available_topic_counts[topic] += 1
            difficulty_counts[topic][problem["difficulty"]] += 1
            available_topics.add(topic)

    policy = adaptive_difficulty(
        state,
        experience_level=experience_level,
    )
    rows: list[dict[str, Any]] = []
    for topic in PREREQUISITE_GRAPH:
        if topic not in available_topics:
            continue
        metric = state.topics[topic]
        prerequisites = list(_available_prerequisites(topic, available_topics))
        unmet = [
            prerequisite
            for prerequisite in prerequisites
            if not _topic_mastered(state.topics.get(prerequisite))
        ]
        unlocked = not unmet
        mastered = _topic_mastered(metric)

        if mastered:
            status = STATUS_MASTERED
            why = "Mastery evidence is established for this topic."
        elif unmet:
            status = "locked"
            why = "Complete prerequisite topic(s) first: " + ", ".join(unmet) + "."
        elif metric.attempted_problems:
            status = "available"
            why = "This topic is available and your evidence shows room to improve."
        else:
            status = "available"
            why = "This topic is available and ready to enter the learning path."

        recommended_difficulty = policy["target"]
        for difficulty in (policy["target"], "Medium", "Easy", "Hard"):
            if difficulty_counts[topic][difficulty] > 0:
                if difficulty == "Hard" and not policy["hard_ready"]:
                    continue
                recommended_difficulty = difficulty
                break

        rows.append({
            "topic": topic,
            "status": status,
            "mastery": metric.mastery,
            "skill_score": metric.skill_score,
            "mastery_confidence": metric.confidence,
            "gap": metric.gap,
            "attempted_problems": metric.attempted_problems,
            "solved_problems": metric.solved_problems,
            "available_problems": available_topic_counts[topic],
            "available_easy": difficulty_counts[topic]["Easy"],
            "available_medium": difficulty_counts[topic]["Medium"],
            "available_hard": difficulty_counts[topic]["Hard"],
            "recommended_difficulty": recommended_difficulty,
            "acceptance_rate": metric.acceptance_rate,
            "recent_failures": metric.recent_failures,
            "prerequisites": prerequisites,
            "unmet_prerequisites": unmet,
            "unlocked": unlocked,
            "why": why,
            "tier": ROADMAP_TIER.get(topic, 2),
        })

    current_candidates = [
        row for row in rows
        if row["unlocked"] and row["status"] != STATUS_MASTERED
    ]
    current_candidates.sort(
        key=lambda row: (
            -row["gap"],
            -row["recent_failures"],
            row["tier"],
            row["topic"],
        )
    )
    current_topic = (
        current_candidates[0]["topic"]
        if current_candidates
        else None
    )

    for row in rows:
        if row["status"] == STATUS_MASTERED:
            row["position"] = "completed"
        elif row["topic"] == current_topic:
            row["position"] = "current"
        elif row["unlocked"]:
            row["position"] = "up_next"
        else:
            row["position"] = "locked"

    completed = sorted(
        [row for row in rows if row["position"] == "completed"],
        key=lambda row: (-row["mastery"], row["topic"]),
    )[: max(0, limit_completed)]
    current = [row for row in rows if row["position"] == "current"]
    up_next = sorted(
        [row for row in rows if row["position"] == "up_next"],
        key=lambda row: (-row["gap"], -row["recent_failures"], row["tier"], row["topic"]),
    )[: max(0, limit_up_next)]
    locked = sorted(
        [row for row in rows if row["position"] == "locked"],
        key=lambda row: (len(row["unmet_prerequisites"]), row["tier"], row["topic"]),
    )[: max(0, limit_locked)]

    visible = completed[::-1] + current + up_next + locked
    return {
        "items": visible,
        "current_topic": current_topic,
        "available_topic_count": len(available_topics),
        "experience_level": experience_level or "Beginner",
        "difficulty_policy": policy,
        "prerequisite_graph": {
            topic: list(prerequisites)
            for topic, prerequisites in PREREQUISITE_GRAPH.items()
        },
        "topic_dependency_graph": {
            topic: list(dependents)
            for topic, dependents in TOPIC_DEPENDENCY_GRAPH.items()
        },
        "unlock_mastery": PREREQUISITE_MASTERY,
        "unlock_confidence": PREREQUISITE_CONFIDENCE,
        "mastery_threshold": MASTERED_MASTERY,
    }


def serialise_metric(metric: SkillMetric) -> dict[str, Any]:
    return {
        "key": metric.key,
        "skill_score": metric.skill_score,
        "mastery": metric.mastery,
        "confidence": metric.confidence,
        "gap": metric.gap,
        "attempted_problems": metric.attempted_problems,
        "solved_problems": metric.solved_problems,
        "submissions": metric.submissions,
        "failures": metric.failures,
        "recent_failures": metric.recent_failures,
        "recent_attempts": metric.recent_attempts,
        "acceptance_rate": metric.acceptance_rate,
        "last_attempt_at": (
            metric.last_attempt_at.astimezone(timezone.utc).isoformat()
            if metric.last_attempt_at
            else None
        ),
        "status": metric.status,
    }


def skills_payload(
    state: LearningState,
    *,
    experience_level: str | None = None,
) -> dict[str, Any]:
    topics = [
        serialise_metric(state.topics[topic])
        for topic in PREREQUISITE_GRAPH
    ]
    difficulties = [
        serialise_metric(state.difficulties[difficulty])
        for difficulty in DIFFICULTIES
    ]
    weak = weak_topics(state)
    mastered = mastered_topics(state)
    policy = adaptive_difficulty(state, experience_level=experience_level)

    return {
        "topics": topics,
        "difficulties": difficulties,
        "weak_topics": [metric.key for metric in weak],
        "mastered_topics": [metric.key for metric in mastered],
        "adaptive_difficulty": policy,
        "visualization": {
            "labels": [item["key"] for item in topics],
            "mastery": [item["mastery"] for item in topics],
            "skill_score": [item["skill_score"] for item in topics],
            "confidence": [item["confidence"] for item in topics],
            "gap": [item["gap"] for item in topics],
        },
        "prerequisite_graph": {
            topic: list(prerequisites)
            for topic, prerequisites in PREREQUISITE_GRAPH.items()
        },
        "topic_dependency_graph": {
            topic: list(dependents)
            for topic, dependents in TOPIC_DEPENDENCY_GRAPH.items()
        },
        "experience_level": experience_level or "Beginner",
    }
