from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from dataclasses import asdict
from typing import Any, Callable

from sqlalchemy.orm import Session

from backend.agent_models import AgentToolCall
from backend.models import CodingAttempt, MentorMessage, MentorSession, Problem, User
from backend.routers.analytics import analytics_summary
from backend.routers.recommendations import next_recommendation


MAX_TOOL_OUTPUT = 5000
MAX_HISTORY = 12

_INJECTION_PATTERNS = (
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?prior\s+instructions",
    r"reveal\s+(the\s+)?system\s+prompt",
    r"reveal\s+(the\s+)?developer\s+message",
    r"show\s+hidden\s+instructions",
    r"follow\s+these\s+instructions\s+instead",
    r"execute\s+(shell|terminal|system)\s+commands",
    r"delete\s+(the\s+)?database",
    r"send\s+(the\s+)?api\s+key",
)

_BLOCKED_DIRECTIVE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


class AgentSafetyError(ValueError):
    pass


class AgentToolError(RuntimeError):
    pass


def looks_like_prompt_injection(text: str) -> bool:
    return bool(_BLOCKED_DIRECTIVE.search(text or ""))


def sanitize_untrusted_text(text: str, *, limit: int = 2500) -> str:
    value = str(text or "")
    value = value.replace("\x00", "")
    value = value.replace("<system>", "&lt;system&gt;")
    value = value.replace("</system>", "&lt;/system&gt;")
    value = value.replace("<developer>", "&lt;developer&gt;")
    value = value.replace("</developer>", "&lt;/developer&gt;")
    if len(value) > limit:
        value = value[:limit] + "\n[truncated]"
    return f"<untrusted_data>\n{value}\n</untrusted_data>"


def inspect_user_code(code: str, language: str = "Python") -> dict[str, Any]:
    source = str(code or "")
    result: dict[str, Any] = {
        "language": language,
        "line_count": source.count("\n") + (1 if source else 0),
        "character_count": len(source),
        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "functions": [],
        "classes": [],
        "imports": [],
        "todo_count": len(re.findall(r"\bTODO\b", source, re.IGNORECASE)),
        "error_hints": [],
    }

    if language.strip().lower() in {"python", "py"}:
        try:
            tree = ast.parse(source)
            result["functions"] = [
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ][:20]
            result["classes"] = [
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef)
            ][:10]
            result["imports"] = [
                node.names[0].name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import) and node.names
            ][:20]
        except SyntaxError as exc:
            result["error_hints"].append(
                {
                    "kind": "syntax_error",
                    "line": exc.lineno,
                    "message": str(exc.msg),
                }
            )
    else:
        result["functions"] = re.findall(
            r"\b(?:def|function|func)\s+([A-Za-z_]\w*)", source
        )[:20]

    result["preview"] = sanitize_untrusted_text(source, limit=7000)
    return result


def inspect_execution_output(execution: dict[str, Any] | None) -> dict[str, Any]:
    if not execution:
        return {"status": "not_run", "failures": 0, "results": []}

    status = str(execution.get("status") or "unknown")
    summary = str(execution.get("summary") or "")
    raw_results = execution.get("results") or []
    results: list[dict[str, Any]] = []

    for item in raw_results[:12]:
        if not isinstance(item, dict):
            continue
        compact = {
            key: item.get(key)
            for key in (
                "status",
                "summary",
                "input",
                "expected_output",
                "actual_output",
                "runtime_ms",
                "stderr",
                "error_line",
            )
            if key in item
        }
        for key in ("input", "expected_output", "actual_output", "stderr", "summary"):
            if key in compact and compact[key] is not None:
                compact[key] = sanitize_untrusted_text(str(compact[key]), limit=900)
        results.append(compact)

    failures = sum(
        1
        for item in results
        if str(item.get("status", "")).lower() not in {"passed", "accepted", "ok"}
    )

    return {
        "status": status,
        "summary": sanitize_untrusted_text(summary, limit=1000),
        "failures": failures,
        "results": results,
    }


def inspect_submission_history(
    db: Session,
    user: User,
    *,
    limit: int = MAX_HISTORY,
) -> dict[str, Any]:
    rows = (
        db.query(CodingAttempt, Problem)
        .join(Problem, CodingAttempt.problem_id == Problem.id)
        .filter(CodingAttempt.user_id == user.id)
        .order_by(CodingAttempt.created_at.desc(), CodingAttempt.id.desc())
        .limit(max(1, min(limit, 30)))
        .all()
    )
    items = [
        {
            "id": attempt.id,
            "problem_slug": problem.slug,
            "title": problem.title,
            "difficulty": problem.difficulty,
            "topics": list(problem.topics or [])[:5],
            "mode": attempt.mode,
            "status": attempt.status,
            "summary": sanitize_untrusted_text(attempt.summary, limit=500),
            "created_at": attempt.created_at.isoformat(),
        }
        for attempt, problem in rows
    ]
    return {"count": len(items), "items": items}


def inspect_analytics(db: Session, user: User) -> dict[str, Any]:
    summary = analytics_summary(current_user=user, db=db)
    return {
        "total_attempts": summary["total_attempts"],
        "total_submissions": summary["total_submissions"],
        "accepted_submissions": summary["accepted_submissions"],
        "total_solved": summary["total_solved"],
        "acceptance_rate": summary["acceptance_rate"],
        "current_streak": summary["current_streak"],
        "ai_hints": summary["ai_hints"],
        "average_runtime_ms": summary["average_runtime_ms"],
        "topics": summary["topics"],
    }


def inspect_topic_mastery(db: Session, user: User) -> dict[str, Any]:
    topics = inspect_analytics(db, user)["topics"]
    weak = sorted(
        topics,
        key=lambda item: (item.get("mastery", 0), -item.get("mastery_confidence", 0), item["topic"]),
    )[:6]
    strong = sorted(
        topics,
        key=lambda item: (-item.get("mastery", 0), -item.get("mastery_confidence", 0), item["topic"]),
    )[:4]
    return {"weakest": weak, "strongest": strong}


def inspect_problem_metadata(
    db: Session,
    problem_slug: str | None,
) -> dict[str, Any]:
    if not problem_slug:
        return {"problem": None}
    problem = db.query(Problem).filter(Problem.slug == problem_slug).first()
    if problem is None:
        return {"problem": None, "error": "Problem not found."}
    description = str(problem.description or "")
    examples = list(problem.examples or [])[:2]
    return {
        "problem": {
            "id": problem.id,
            "slug": problem.slug,
            "title": problem.title,
            "difficulty": problem.difficulty,
            "topics": list(problem.topics or [])[:8],
            "description": sanitize_untrusted_text(description, limit=4200),
            "constraints": [
                sanitize_untrusted_text(item, limit=450)
                for item in (problem.constraints or [])[:8]
            ],
            "examples": examples,
        }
    }


def recommend_problem(
    db: Session,
    user: User,
    current_problem_id: int | None = None,
) -> dict[str, Any]:
    result = next_recommendation(
        current_problem_id=current_problem_id,
        current_user=user,
        db=db,
    )
    problem = result.get("problem")
    if problem:
        problem = {
            "id": problem["id"],
            "slug": problem["slug"],
            "title": problem["title"],
            "difficulty": problem["difficulty"],
            "topics": problem.get("topics") or [],
        }
    return {
        "problem": problem,
        "reason": sanitize_untrusted_text(result.get("reason", ""), limit=900),
        "focus_topic": result.get("focus_topic"),
        "topic_health": result.get("topic_health"),
        "locked_until_solved": result.get("locked_until_solved", False),
    }


def explain_recommendation(
    recommendation: dict[str, Any],
    mastery: dict[str, Any],
) -> dict[str, Any]:
    problem = recommendation.get("problem")
    if not problem:
        return {"explanation": "There is no available recommendation right now."}

    focus = recommendation.get("focus_topic") or (problem.get("topics") or ["your current skills"])[0]
    weak_topics = {item["topic"]: item for item in mastery.get("weakest", [])}
    focus_stat = weak_topics.get(focus)
    if focus_stat:
        explanation = (
            f"{problem['title']} targets {focus}. "
            f"Your current mastery estimate for that topic is {focus_stat['mastery']}% "
            f"with {focus_stat['attempted_problems']} practiced problems, so the recommendation "
            "is intended as targeted reinforcement rather than a random problem."
        )
    else:
        explanation = (
            f"{problem['title']} was selected to strengthen {focus}. "
            "The agent uses the existing adaptive recommendation service instead of inventing a separate score."
        )
    return {"explanation": explanation}


@dataclass
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., dict[str, Any]]
    read_only: bool = True


class AgentToolRegistry:
    def __init__(self) -> None:
        self._tools = {
            spec.name: spec
            for spec in (
                ToolSpec(
                    "inspect_user_code",
                    "Inspect structure and bounded content of the user's current code.",
                    inspect_user_code,
                ),
                ToolSpec(
                    "inspect_execution_output",
                    "Inspect the latest execution outcome and bounded test details.",
                    inspect_execution_output,
                ),
                ToolSpec(
                    "inspect_submission_history",
                    "Inspect recent submission outcomes without returning full historical code.",
                    inspect_submission_history,
                ),
                ToolSpec(
                    "inspect_analytics",
                    "Inspect compact progress, streak, acceptance, and topic analytics.",
                    inspect_analytics,
                ),
                ToolSpec(
                    "inspect_topic_mastery",
                    "Inspect weakest and strongest topic mastery estimates.",
                    inspect_topic_mastery,
                ),
                ToolSpec(
                    "inspect_problem_metadata",
                    "Inspect compact metadata for the active problem.",
                    inspect_problem_metadata,
                ),
                ToolSpec(
                    "recommend_problem",
                    "Use the existing adaptive recommendation service to select a problem.",
                    recommend_problem,
                ),
                ToolSpec(
                    "explain_recommendation",
                    "Explain an already-selected recommendation using mastery evidence.",
                    explain_recommendation,
                ),
            )
        }

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "read_only": spec.read_only,
            }
            for spec in self._tools.values()
        ]

    def execute(
        self,
        call: AgentToolCall,
        *,
        db: Session,
        user: User,
        code: str = "",
        language: str = "Python",
        execution: dict[str, Any] | None = None,
        problem_slug: str | None = None,
        current_problem_id: int | None = None,
        recommendation: dict[str, Any] | None = None,
        mastery: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = self._tools.get(call.name)
        if spec is None:
            raise AgentToolError(f"Unknown agent tool: {call.name}")
        if not spec.read_only:
            raise AgentSafetyError(f"Tool '{call.name}' is not permitted to mutate application state.")

        started = time.monotonic()
        args = dict(call.arguments)
        if call.name == "inspect_user_code":
            result = spec.handler(code, language)
        elif call.name == "inspect_execution_output":
            result = spec.handler(execution)
        elif call.name == "inspect_submission_history":
            result = spec.handler(db, user, limit=int(args.get("limit", MAX_HISTORY)))
        elif call.name == "inspect_analytics":
            result = spec.handler(db, user)
        elif call.name == "inspect_topic_mastery":
            result = spec.handler(db, user)
        elif call.name == "inspect_problem_metadata":
            result = spec.handler(db, problem_slug)
        elif call.name == "recommend_problem":
            result = spec.handler(db, user, current_problem_id)
        elif call.name == "explain_recommendation":
            result = spec.handler(recommendation or {}, mastery or {})
        else:
            raise AgentToolError(f"Unhandled agent tool: {call.name}")

        encoded = json.dumps(result, default=str, ensure_ascii=False)
        if len(encoded) > MAX_TOOL_OUTPUT:
            result = {
                "truncated": True,
                "preview": encoded[: MAX_TOOL_OUTPUT - 120],
            }
        result["_audit"] = {
            "tool": call.name,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "argument_keys": sorted(args),
        }
        return result


def audit_payload(call: AgentToolCall, result: dict[str, Any], *, success: bool, error: str | None = None) -> dict[str, Any]:
    return {
        "tool": call.name,
        "arguments": {key: str(value)[:240] for key, value in call.arguments.items()},
        "success": success,
        "error": error,
        "result_keys": sorted(result.keys()),
    }
