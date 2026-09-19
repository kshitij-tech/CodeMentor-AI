from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Problem, User
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/problems", tags=["Problems"])

def serialize(problem: Problem) -> dict:
    return {
        "id": problem.id,
        "slug": problem.slug,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "topics": problem.topics,
        "description": problem.description,
        "constraints": problem.constraints,
        "examples": problem.examples,
        "starter_code": problem.starter_code,
        "source": problem.source,
        "external_id": problem.external_id,
        "external_url": problem.external_url,
        "execution_mode": problem.execution_mode,
        "time_limit_ms": problem.time_limit_ms,
        "memory_limit_mb": problem.memory_limit_mb,
        "validation": problem.validation,
        "package_metadata": problem.package_metadata,
    }

@router.get("")
def list_problems(
    topic: str | None = Query(default=None),
    difficulty: str | None = Query(default=None),
    source: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problems = db.query(Problem).order_by(Problem.id.asc()).all()
    if topic:
        problems = [p for p in problems if topic in (p.topics or [])]
    if difficulty:
        problems = [p for p in problems if p.difficulty.lower() == difficulty.lower()]
    if source:
        problems = [p for p in problems if p.source.lower() == source.lower()]
    return {"items": [serialize(problem) for problem in problems]}

@router.get("/{slug}")
def get_problem(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problem = db.query(Problem).filter(Problem.slug == slug).first()
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found.")
    return serialize(problem)
