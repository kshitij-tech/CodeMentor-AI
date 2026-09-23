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
from backend.stdio_adapter import (
    adapt_stdio_source,
    editor_schema_from_metadata,
)


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

    from backend.problem_catalog import infer_execution_mode, function_editor_schema_from_problem

    actual_mode = infer_execution_mode(
        problem.execution_mode,
        test_cases=problem.test_cases,
        starter_code=problem.starter_code,
        examples=problem.examples,
    )

    time_limit_seconds = min(
        10.0,
        max(0.1, float(problem.time_limit_ms or 2000) / 1000),
    )
    memory_limit_mb = (
        min(1024, max(64, int(problem.memory_limit_mb)))
        if problem.memory_limit_mb
        else None
    )

    if actual_mode == "stdio":
        metadata = problem.package_metadata or {}
        cases = problem.test_cases or []

        # Do not rely only on the historical judge_supported import flag.
        # Standard .in/.ans test cases can be judged by the default validator
        # even when older package metadata marked the record unsupported.
        uses_custom_validator = any(
            bool(case.get("validator_name"))
            for case in cases
        )
        type_values = set(str(item).lower() for item in (metadata.get("type") or []))
        validation_text = str(metadata.get("validation") or "").lower()
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

        if unsupported_format or (uses_custom_validator and not metadata.get("judge_supported", False)):
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

        if request.mode == "run":
            sample_cases = [
                case for case in cases if case.get("visibility") == "sample"
            ]
            cases = sample_cases or cases

        try:
            package_metadata = problem.package_metadata or {}
            editor_schema = editor_schema_from_metadata(
                package_metadata,
                problem.description,
                problem.examples,
            )
            execution_source = adapt_stdio_source(
                request.code,
                request.language,
                editor_schema,
            )
            if request.language == "Python":
                outcomes = run_python_stdio_tests(
                    execution_source,
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
                    execution_source,
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
    else:
        cases = problem.test_cases or []
        if request.mode == "run":
            sample_cases = [
                case for case in cases if case.get("visibility") == "sample"
            ]
            cases = sample_cases or cases
        try:
            function_schema = function_editor_schema_from_problem(
                problem.starter_code,
                cases,
                problem.examples,
                problem.description,
                explicit_schema=(problem.package_metadata or {}).get("editor_input_schema"),
            )
            parameter_count = len(function_schema)
            if request.language == "Python":
                outcomes = run_python_tests(
                    request.code,
                    cases,
                    time_limit_seconds=time_limit_seconds,
                    memory_limit_mb=memory_limit_mb,
                )
            else:
                outcomes = run_language_function_tests(
                    request.code,
                    request.language,
                    cases,
                    parameter_count=parameter_count,
                    time_limit_seconds=time_limit_seconds,
                    memory_limit_mb=memory_limit_mb,
                )
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
