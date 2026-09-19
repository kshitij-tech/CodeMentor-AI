from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Problem, User
from backend.routers.auth import get_current_user
from backend.execution import CodeRejectedError, run_python_tests


router = APIRouter(prefix="/execution", tags=["Execution"])


class ExecuteRequest(BaseModel):
    problem_slug: str = Field(min_length=1, max_length=120)
    language: Literal["Python", "C++", "Java", "JavaScript", "TypeScript", "Go", "Rust"]
    code: str = Field(min_length=1, max_length=40000)
    mode: Literal["run", "submit"] = "run"


@router.post("/run")
def execute_code(
    request: ExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if request.language != "Python":
        return {
            "status": "Unsupported Language",
            "summary": "Python execution is available in this stage. Other language runtimes will be added next.",
            "results": [],
        }

    problem = (
        db.query(Problem)
        .filter(Problem.slug == request.problem_slug)
        .first()
    )
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found.")

    try:
        outcomes = run_python_tests(request.code, problem.test_cases or [])
    except CodeRejectedError as exc:
        return {
            "status": "Rejected",
            "summary": str(exc),
            "results": [],
        }

    passed = sum(outcome.passed for outcome in outcomes)
    total = len(outcomes)
    overall = "Accepted" if total and passed == total else "Wrong Answer"

    if any(outcome.status == "Time Limit Exceeded" for outcome in outcomes):
        overall = "Time Limit Exceeded"
    elif any(outcome.status == "Runtime Error" for outcome in outcomes):
        overall = "Runtime Error"

    return {
        "status": overall,
        "summary": f"{passed}/{total} tests passed.",
        "mode": request.mode,
        "results": [
            {
                "test": outcome.index,
                "passed": outcome.passed,
                "status": outcome.status,
                "expected": outcome.expected,
                "actual": outcome.actual,
                "runtime_ms": outcome.runtime_ms,
                "message": outcome.message,
            }
            for outcome in outcomes
        ],
    }
