import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Problem, User, CodingAttempt
from backend.routers.auth import get_current_user
from backend.execution import (
    CodeRejectedError,
    extract_error_line,
    extract_error_location,
    run_language_function_tests,
    run_language_stdio_tests,
    run_python_stdio_tests,
    run_python_tests,
    syntax_diagnostic,
)
from backend.stdio_adapter import editor_schema_from_metadata


router = APIRouter(prefix="/execution", tags=["Execution"])


class ExecuteRequest(BaseModel):
    problem_slug: str = Field(min_length=1, max_length=120)
    language: Literal["Python", "C++", "Java", "JavaScript", "TypeScript", "Go", "Rust"]
    code: str = Field(min_length=1, max_length=40000)
    mode: Literal["run", "submit"] = "run"


@router.post("/validate")
def validate_syntax(
    request: ExecuteRequest,
    current_user: User = Depends(get_current_user),
):
    if request.language == "Python":
        return syntax_diagnostic(request.code)

    # Monaco provides native syntax diagnostics for JavaScript/TypeScript.
    # Other languages will be validated by their sandboxed compiler/runtime
    # once those runtimes are enabled.
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

    # Every problem is now judged as a normal stdin/stdout program.
    # Legacy callable test cases are converted to a single JSON input document,
    # so the user's code is always responsible for parsing stdin itself.
    cases = []
    for original_case in (problem.test_cases or []):
        case = dict(original_case)
        if "args" in case and "input" not in case:
            case["input"] = json.dumps(
                case.get("args", []),
                ensure_ascii=True,
                separators=(",", ":"),
            )
        if "expected" in case and "expected_output" not in case:
            case["expected_output"] = json.dumps(
                case.get("expected"),
                ensure_ascii=True,
                separators=(",", ":"),
            )
        cases.append(case)

    if request.mode == "run":
        sample_cases = [
            case for case in cases if case.get("visibility") == "sample"
        ]
        cases = sample_cases or cases

    try:
        package_metadata = problem.package_metadata or {}
        uses_custom_validator = any(
            bool(case.get("validator_name"))
            for case in cases
        )
        type_values = set(str(item).lower() for item in (package_metadata.get("type") or []))
        validation_text = str(package_metadata.get("validation") or "").lower()
        unsupported_format = bool(
            {"interactive", "multi-pass", "submit-answer", "score"} & type_values
            or any(
                token in validation_text.split()
                for token in {"interactive", "score"}
            )
        )

        if request.language != "Python" and uses_custom_validator:
            return {
                "status": "Unsupported Problem Format",
                "summary": (
                    "This problem uses a custom validator that is currently "
                    "available only through the Python judge path."
                ),
                "error_line": None,
                "error_column": None,
                "results": [],
            }

        if unsupported_format or (
            uses_custom_validator
            and not package_metadata.get("judge_supported", False)
        ):
            return {
                "status": "Unsupported Problem Format",
                "summary": (
                    "This problem uses an interactive, scoring, or custom validator "
                    "that is not supported by the current execution runner."
                ),
                "error_line": None,
                "error_column": None,
                "results": [],
            }

        if request.language == "Python":
            outcomes = run_python_stdio_tests(
                request.code,
                cases,
                time_limit_seconds=time_limit_seconds,
                memory_limit_mb=memory_limit_mb,
                package_root=package_metadata.get("package_root"),
                validation_time_seconds=max(
                    0.1,
                    float(package_metadata.get("validation_time_ms", 60000)) / 1000,
                ),
                validation_output_bytes=max(
                    1024,
                    int(package_metadata.get("validation_output_bytes", 8 * 1024 * 1024)),
                ),
            )
        else:
            outcomes = run_language_stdio_tests(
                request.code,
                request.language,
                cases,
                time_limit_seconds=time_limit_seconds,
                memory_limit_mb=memory_limit_mb,
            )
    except ValueError as exc:
        return {
            "status": "Rejected",
            "summary": str(exc),
            "error_line": None,
            "error_column": None,
            "results": [],
        }
    except FileNotFoundError:
        return {
            "status": "Runtime Unavailable",
            "summary": (
                f"The {request.language} runtime is not installed or configured "
                "on the execution host."
            ),
            "error_line": None,
            "error_column": None,
            "results": [],
        }
    except CodeRejectedError as exc:
        return {
            "status": "Rejected",
            "summary": str(exc),
            "error_line": extract_error_line(str(exc)),
            "error_column": (
                extract_error_location(str(exc))[1]
                if extract_error_location(str(exc))
                else None
            ),
            "results": [],
        }

    passed = sum(outcome.passed for outcome in outcomes)
    total = len(outcomes)
    overall = "Accepted" if total and passed == total else "Wrong Answer"

    if any(outcome.status == "Judge Error" for outcome in outcomes):
        overall = "Judge Error"
    elif any(outcome.status == "Time Limit Exceeded" for outcome in outcomes):
        overall = "Time Limit Exceeded"
    elif any(outcome.status == "Output Limit Exceeded" for outcome in outcomes):
        overall = "Output Limit Exceeded"
    elif any(outcome.status == "Compile Error" for outcome in outcomes):
        overall = "Compile Error"
    elif any(outcome.status == "Runtime Error" for outcome in outcomes):
        overall = "Runtime Error"

    summary = f"{passed}/{total} tests passed."

    stored_results = []
    public_results = []
    for index, outcome in enumerate(outcomes):
        case = cases[index] if index < len(cases) else {}
        visibility = case.get("visibility")
        result = {
            "test": outcome.index,
            "passed": outcome.passed,
            "status": outcome.status,
            "visibility": visibility,
            "expected": outcome.expected,
            "actual": outcome.actual,
            "runtime_ms": outcome.runtime_ms,
            "message": outcome.message,
            "error_line": extract_error_line(outcome.message),
            "error_column": (
                extract_error_location(outcome.message)[1]
                if extract_error_location(outcome.message)
                else None
            ),
        }
        stored_results.append(result)
        public_results.append(
            {
                **result,
                "expected": None if visibility == "secret" else outcome.expected,
            }
        )

    error_line = next(
        (result["error_line"] for result in public_results if result["error_line"] is not None),
        None,
    )
    error_column = next(
        (result["error_column"] for result in public_results if result["error_column"] is not None),
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
