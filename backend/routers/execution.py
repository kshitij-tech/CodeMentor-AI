from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import CodingAttempt, Problem, User
from backend.routers.auth import get_current_user
from backend.execution import (
    CodeRejectedError,
    SandboxUnavailableError,
    extract_error_line,
    extract_error_location,
    run_language_stdio_tests,
    run_python_stdio_tests,
    overall_status,
    syntax_diagnostic,
)

router = APIRouter(prefix="/execution", tags=["Execution"])


class ExecuteRequest(BaseModel):
    problem_slug: str = Field(min_length=1, max_length=120)
    language: Literal["Python", "C++", "Java", "JavaScript", "TypeScript", "Go", "Rust"]
    code: str = Field(min_length=1, max_length=40000)
    mode: Literal["run", "submit"] = "run"


def _error_response(status: str, summary: str) -> dict:
    return {
        "status": status,
        "summary": summary,
        "error_line": extract_error_line(summary),
        "error_column": (
            extract_error_location(summary)[1]
            if extract_error_location(summary)
            else None
        ),
        "results": [],
    }


@router.post("/validate")
def validate_syntax(
    request: ExecuteRequest,
    current_user: User = Depends(get_current_user),
):
    del current_user
    if request.language == "Python":
        return syntax_diagnostic(request.code)
    return {
        "valid": True,
        "message": None,
        "line": None,
        "column": None,
        "end_line": None,
        "end_column": None,
    }


@router.post("/run")
def execute_code(
    request: ExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problem = (
        db.query(Problem)
        .filter(Problem.slug == request.problem_slug)
        .first()
    )
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found.")

    if str(problem.execution_mode or "stdio").strip().lower() != "stdio":
        return _error_response(
            "System Error",
            "This problem is not configured for competitive-programming stdin/stdout execution. "
            "Migrate its test data to execution_mode=stdio.",
        )

    cases = [dict(case) for case in (problem.test_cases or [])]
    if not cases:
        return _error_response(
            "System Error",
            "The problem contains no executable test cases.",
        )

    if request.mode == "run":
        sample_cases = [
            case for case in cases if case.get("visibility") == "sample"
        ]
        cases = sample_cases or cases

    package_metadata = problem.package_metadata or {}
    uses_custom_validator = any(
        bool(case.get("validator_name")) for case in cases
    )
    validation_mode = str(
        package_metadata.get("validation") or ""
    ).strip().lower()
    if uses_custom_validator or validation_mode == "custom":
        return _error_response(
            "System Error",
            "Custom validators are not executed by the code-execution sandbox yet. "
            "Use the default validator for this execution service.",
        )

    type_values = {
        str(item).lower() for item in (package_metadata.get("type") or [])
    }
    unsupported_format = bool(
        {"interactive", "multi-pass", "submit-answer", "score"} & type_values
        or any(
            token in validation_mode.split()
            for token in {"interactive", "score"}
        )
    )
    if unsupported_format or not package_metadata.get("judge_supported", True):
        return _error_response(
            "System Error",
            "This problem format is not supported by the stdin/stdout execution service.",
        )

    time_limit_seconds = min(
        10.0,
        max(0.1, float(problem.time_limit_ms or 2000) / 1000),
    )
    memory_limit_mb = problem.memory_limit_mb

    try:
        if request.language == "Python":
            outcomes = run_python_stdio_tests(
                request.code,
                cases,
                time_limit_seconds=time_limit_seconds,
                memory_limit_mb=memory_limit_mb,
            )
        else:
            outcomes = run_language_stdio_tests(
                request.code,
                request.language,
                cases,
                time_limit_seconds=time_limit_seconds,
                memory_limit_mb=memory_limit_mb,
            )
    except SandboxUnavailableError as exc:
        return _error_response("System Error", str(exc))
    except CodeRejectedError as exc:
        return _error_response("System Error", str(exc))
    except (OSError, ValueError) as exc:
        return _error_response("System Error", str(exc))

    overall = overall_status(outcomes)
    passed = sum(outcome.passed for outcome in outcomes)
    total = len(outcomes)
    summary = f"{passed}/{total} tests passed."

    public_results = []
    stored_results = []
    for index, outcome in enumerate(outcomes):
        case = cases[index] if index < len(cases) else {}
        visibility = case.get("visibility")
        error_location = extract_error_location(outcome.message)
        result = {
            "test": outcome.index,
            "passed": outcome.passed,
            "status": outcome.status,
            "visibility": visibility,
            "expected": outcome.expected,
            "actual": outcome.actual,
            "runtime_ms": outcome.runtime_ms,
            "message": outcome.message,
            "error_line": error_location[0] if error_location else None,
            "error_column": error_location[1] if error_location else None,
        }
        stored_results.append(result)
        public_results.append(
            {
                **result,
                "expected": None if visibility == "secret" else outcome.expected,
            }
        )

    error_line = next(
        (
            item["error_line"]
            for item in public_results
            if item["error_line"] is not None
        ),
        None,
    )
    error_column = next(
        (
            item["error_column"]
            for item in public_results
            if item["error_column"] is not None
        ),
        None,
    )

    attempt = CodingAttempt(
        user_id=current_user.id,
        problem_id=problem.id,
        language=request.language,
        mode=request.mode,
        code=request.code,
        status=overall,
        summary=summary,
        results=stored_results,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    return {
        "attempt_id": attempt.id,
        "status": overall,
        "summary": summary,
        "mode": request.mode,
        "error_line": error_line,
        "error_column": error_column,
        "results": public_results,
    }
