from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentPlan:
    goal: str
    tool_calls: tuple[AgentToolCall, ...]
    approval_required: bool = False
    safety_flags: tuple[str, ...] = ()


@dataclass
class LearningState:
    total_attempts: int = 0
    total_submissions: int = 0
    total_solved: int = 0
    current_streak: int = 0
    focus_topics: list[dict[str, Any]] = field(default_factory=list)
    recurring_mistakes: list[dict[str, Any]] = field(default_factory=list)
    conceptual_risks: list[dict[str, Any]] = field(default_factory=list)
    recent_activity: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentResult:
    answer: str
    plan: AgentPlan
    tool_results: dict[str, Any]
    learning_state: LearningState
    approval_required: bool = False
    patch: dict[str, Any] | None = None
    error_line: int | None = None
