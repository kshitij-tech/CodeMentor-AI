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
        "package_metadata": {
            key: value
            for key, value in (problem.package_metadata or {}).items()
            if key != "package_root"
        },
    }

@router.get("")
def list_problems(
    topic: str | None = Query(default=None),
    difficulty: str | None = Query(default=None),
    source: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=120),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Problem).order_by(Problem.id.asc())

    if difficulty:
        query = query.filter(Problem.difficulty.ilike(difficulty))

    if source:
        query = query.filter(Problem.source.ilike(source))

    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            Problem.title.ilike(pattern)
            | Problem.description.ilike(pattern)
        )

    if topic:
        # JSON topic filtering is kept in Python for SQLite/PostgreSQL parity.
        total_candidates = query.all()
        filtered = [p for p in total_candidates if topic in (p.topics or [])]
        total = len(filtered)
        page = filtered[offset:offset + limit]
    else:
        total = query.count()
        page = query.offset(offset).limit(limit).all()

    # Problem lists never need hidden test cases or package internals.
    items = []
    for problem in page:
        item = serialize(problem)
        item.pop("test_cases", None)
        item.pop("package_metadata", None)
        items.append(item)

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }

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
