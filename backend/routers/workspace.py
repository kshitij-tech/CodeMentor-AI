from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import CodingAttempt, CodeWorkspace, Problem, User
from backend.routers.auth import get_current_user


router = APIRouter(prefix="/workspace", tags=["Workspace"])

SUPPORTED_LANGUAGES = {
    "Python",
    "C++",
    "Java",
    "JavaScript",
    "TypeScript",
    "Go",
    "Rust",
}


class WorkspaceUpdateRequest(BaseModel):
    problem_slug: str = Field(min_length=1, max_length=120)
    language: str = Field(min_length=1, max_length=50)
    code: str = Field(max_length=40000)


def _problem(
    problem_slug: str,
    db: Session,
) -> Problem:
    problem = (
        db.query(Problem)
        .filter(Problem.slug == problem_slug)
        .first()
    )
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found.")
    return problem


def _validate_language(language: str) -> str:
    value = language.strip()
    if value not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported language.")
    return value


@router.get("")
def get_workspace(
    problem_slug: str = Query(min_length=1, max_length=120),
    language: str = Query(min_length=1, max_length=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problem = _problem(problem_slug, db)
    language = _validate_language(language)

    workspace = (
        db.query(CodeWorkspace)
        .filter(
            CodeWorkspace.user_id == current_user.id,
            CodeWorkspace.problem_id == problem.id,
            CodeWorkspace.language == language,
        )
        .first()
    )

    return {
        "problem_slug": problem.slug,
        "language": language,
        "code": workspace.code if workspace else None,
        "updated_at": (
            workspace.updated_at.isoformat()
            if workspace
            else None
        ),
        "source": "server" if workspace else None,
    }


@router.put("")
def save_workspace(
    request: WorkspaceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problem = _problem(request.problem_slug, db)
    language = _validate_language(request.language)

    workspace = (
        db.query(CodeWorkspace)
        .filter(
            CodeWorkspace.user_id == current_user.id,
            CodeWorkspace.problem_id == problem.id,
            CodeWorkspace.language == language,
        )
        .first()
    )

    now = datetime.now(timezone.utc)
    if workspace is None:
        workspace = CodeWorkspace(
            user_id=current_user.id,
            problem_id=problem.id,
            language=language,
            code=request.code,
            updated_at=now,
        )
        db.add(workspace)
    else:
        workspace.code = request.code
        workspace.updated_at = now

    db.commit()
    db.refresh(workspace)

    return {
        "problem_slug": problem.slug,
        "language": language,
        "code": workspace.code,
        "updated_at": workspace.updated_at.isoformat(),
        "source": "server",
    }


@router.get("/history")
def workspace_history(
    problem_slug: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problem = _problem(problem_slug, db)

    attempts = (
        db.query(CodingAttempt)
        .filter(
            CodingAttempt.user_id == current_user.id,
            CodingAttempt.problem_id == problem.id,
        )
        .order_by(CodingAttempt.created_at.desc())
        .limit(limit)
        .all()
    )

    items = []
    for attempt in attempts:
        runtimes = [
            result.get("runtime_ms")
            for result in (attempt.results or [])
            if isinstance(result, dict)
            and isinstance(result.get("runtime_ms"), (int, float))
        ]
        items.append(
            {
                "id": attempt.id,
                "language": attempt.language,
                "mode": attempt.mode,
                "status": attempt.status,
                "summary": attempt.summary,
                "runtime_ms": (
                    round(sum(runtimes) / len(runtimes), 1)
                    if runtimes
                    else None
                ),
                "created_at": attempt.created_at.replace(
                    tzinfo=timezone.utc
                ).isoformat()
                if attempt.created_at.tzinfo is None
                else attempt.created_at.isoformat(),
            }
        )

    return {
        "problem_slug": problem.slug,
        "items": items,
    }
