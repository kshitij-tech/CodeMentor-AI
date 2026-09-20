from collections import Counter
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Problem, User
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/problems", tags=["Problems"])


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _is_english_problem(title: str | None, description: str | None) -> bool:
    text = f"{title or ''}\n{description or ''}"
    return not _CJK_RE.search(text)



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


def serialize_list_row(row) -> dict:
    return {
        "id": row.id,
        "slug": row.slug,
        "title": row.title,
        "difficulty": row.difficulty,
        "topics": row.topics or [],
        "source": row.source,
        "external_id": row.external_id,
        "external_url": row.external_url,
    }


@router.get("")
def list_problems(
    topic: str | None = Query(default=None),
    difficulty: str | None = Query(default=None),
    source: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(
            Problem.id,
            Problem.slug,
            Problem.title,
            Problem.difficulty,
            Problem.topics,
            Problem.description,
            Problem.source,
            Problem.external_id,
            Problem.external_url,
        )
        .order_by(Problem.id.asc())
    )

    if difficulty:
        query = query.filter(Problem.difficulty.ilike(difficulty))

    if source:
        query = query.filter(Problem.source.ilike(source))

    if search:
        query = query.filter(Problem.title.ilike(f"%{search.strip()}%"))

    # Existing databases may contain non-English records from earlier imports.
    # Filter them here so the Practice catalogue stays English-only.
    candidates = query.all()
    candidates = [
        row for row in candidates
        if _is_english_problem(row.title, row.description)
    ]

    if topic:
        candidates = [row for row in candidates if topic in (row.topics or [])]

    total = len(candidates)
    page = candidates[offset : offset + limit]
    items = [serialize_list_row(row) for row in page]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@router.get("/topics")
def list_problem_topics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    topic_counts: Counter[str] = Counter()
    difficulty_counts: Counter[str] = Counter()

    rows = db.query(
        Problem.topics,
        Problem.difficulty,
        Problem.title,
        Problem.description,
    ).yield_per(1000)
    total = 0
    for topics, difficulty, title, description in rows:
        if not _is_english_problem(title, description):
            continue
        total += 1
        difficulty_counts[str(difficulty)] += 1
        for topic in topics or []:
            topic_text = str(topic).strip()
            if topic_text:
                topic_counts[topic_text] += 1

    return {
        "total": total,
        "topics": [
            {"name": name, "count": count}
            for name, count in sorted(
                topic_counts.items(),
                key=lambda item: (-item[1], item[0].lower()),
            )
        ],
        "difficulties": [
            {"name": name, "count": count}
            for name, count in sorted(
                difficulty_counts.items(),
                key=lambda item: item[0].lower(),
            )
        ],
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
