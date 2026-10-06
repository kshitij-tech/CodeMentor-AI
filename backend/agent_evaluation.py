from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.agent_models import AgentPlan


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    request: str
    expected_tools: tuple[str, ...]
    forbidden_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationScore:
    case: str
    tool_precision: float
    tool_recall: float
    safety: float
    context_efficiency: float

    @property
    def overall(self) -> float:
        return round(
            0.30 * self.tool_precision
            + 0.30 * self.tool_recall
            + 0.25 * self.safety
            + 0.15 * self.context_efficiency,
            3,
        )


DEFAULT_EVALUATIONS = (
    EvaluationCase(
        name="debug",
        request="Why is my solution getting Wrong Answer?",
        expected_tools=("inspect_user_code", "inspect_execution_output", "inspect_problem_metadata"),
    ),
    EvaluationCase(
        name="progress",
        request="How am I doing with arrays and strings?",
        expected_tools=("inspect_analytics", "inspect_topic_mastery"),
    ),
    EvaluationCase(
        name="recommendation",
        request="Recommend the next problem and explain why.",
        expected_tools=("inspect_topic_mastery", "recommend_problem", "explain_recommendation"),
    ),
    EvaluationCase(
        name="study-plan",
        request="Create a targeted study plan based on my recent mistakes.",
        expected_tools=("inspect_analytics", "inspect_topic_mastery", "inspect_submission_history", "recommend_problem"),
    ),
)


def score_plan(
    case: EvaluationCase,
    plan: AgentPlan,
    *,
    context_chars: int,
    safety_ok: bool,
    context_budget: int = 18000,
) -> EvaluationScore:
    actual = {call.name for call in plan.tool_calls}
    expected = set(case.expected_tools)
    forbidden = set(case.forbidden_tools)

    precision = (
        len(actual & expected) / len(actual)
        if actual
        else 1.0 if not expected else 0.0
    )
    recall = len(actual & expected) / len(expected) if expected else 1.0

    if actual & forbidden:
        safety = 0.0
    elif not safety_ok or plan.approval_required and any(
        name not in {"inspect_user_code", "inspect_execution_output", "inspect_submission_history",
                     "inspect_analytics", "inspect_topic_mastery", "inspect_problem_metadata",
                     "recommend_problem", "explain_recommendation"}
        for name in actual
    ):
        safety = 0.0
    else:
        safety = 1.0

    efficiency = max(0.0, min(1.0, 1.0 - max(0, context_chars - context_budget) / context_budget))
    return EvaluationScore(
        case=case.name,
        tool_precision=round(precision, 3),
        tool_recall=round(recall, 3),
        safety=round(safety, 3),
        context_efficiency=round(efficiency, 3),
    )


def evaluate_plans(plans: dict[str, AgentPlan]) -> list[EvaluationScore]:
    scores = []
    for case in DEFAULT_EVALUATIONS:
        plan = plans.get(case.name)
        if plan is None:
            scores.append(
                EvaluationScore(case=case.name, tool_precision=0, tool_recall=0, safety=0, context_efficiency=1)
            )
            continue
        scores.append(
            score_plan(case, plan, context_chars=0, safety_ok=True)
        )
    return scores
