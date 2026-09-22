from collections import Counter
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Problem, User
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/problems", tags=["Problems"])


from backend.problem_catalog import (
    CANONICAL_TOPICS,
    TOPIC_HIERARCHY,
    canonicalize_topics,
    ensure_starter_code,
    is_english_problem,
    normalize_difficulty,
    normalize_topic,
    strip_examples_from_description,
)


_CATALOG_CACHE_TTL_SECONDS = 120.0
_catalog_cache: dict[str, object] = {
    "loaded_at": 0.0,
    "rows": [],
    "topics": [],
    "difficulties": [],
    "total": 0,
}


def _catalog_cache_valid() -> bool:
    return (
        bool(_catalog_cache["rows"])
        and time.monotonic() - float(_catalog_cache["loaded_at"]) < _CATALOG_CACHE_TTL_SECONDS
    )


def _build_catalog_cache(db: Session) -> None:
    rows = (
        db.query(
            Problem.id,
            Problem.slug,
            Problem.title,
            Problem.difficulty,
            Problem.topics,
            Problem.source,
            Problem.external_id,
            Problem.external_url,
            Problem.description,
            Problem.execution_mode,
        )
        .filter(Problem.difficulty.isnot(None))
        .order_by(Problem.id.asc())
        .all()
    )

    clean_rows = []
    topic_counts: Counter[str] = Counter()
    difficulty_counts: Counter[str] = Counter()

    for row in rows:
        if not is_english_problem(row.title, row.description):
            continue
        if normalize_difficulty(row.difficulty) is None:
            continue

        normalized_difficulty = normalize_difficulty(row.difficulty)
        normalized_topics = canonicalize_topics(row.topics)
        item = {
            "id": row.id,
            "slug": row.slug,
            "title": row.title,
            "difficulty": normalized_difficulty,
            "topics": normalized_topics,
            "source": row.source,
            "external_id": row.external_id,
            "external_url": row.external_url,
            "execution_mode": row.execution_mode,
        }
        clean_rows.append(item)
        difficulty_counts[normalized_difficulty] += 1

        for topic_text in normalized_topics:
            topic_counts[topic_text] += 1

    _catalog_cache["rows"] = clean_rows
    _catalog_cache["topics"] = [
        {"name": name, "count": count}
        for name, count in sorted(
            topic_counts.items(),
            key=lambda item: (-item[1], item[0].lower()),
        )
    ]
    _catalog_cache["difficulties"] = [
        {"name": name, "count": count}
        for name, count in sorted(
            difficulty_counts.items(),
            key=lambda item: item[0].lower(),
        )
    ]
    _catalog_cache["total"] = len(clean_rows)
    _catalog_cache["loaded_at"] = time.monotonic()


def _catalog_rows(db: Session) -> list[dict]:
    if not _catalog_cache_valid():
        _build_catalog_cache(db)
    return _catalog_cache["rows"]


def prime_problem_catalog(db: Session) -> None:
    _catalog_rows(db)


def _topic_matches(problem_topics: list[str] | None, requested_topic: str) -> bool:
    requested = normalize_topic(requested_topic)
    return requested in canonicalize_topics(problem_topics)


def serialize(problem: Problem) -> dict:
    return {
        "id": problem.id,
        "slug": problem.slug,
        "title": problem.title,
        "difficulty": normalize_difficulty(problem.difficulty),
        "topics": canonicalize_topics(problem.topics),
        "description": strip_examples_from_description(problem.description, problem.examples),
        "constraints": problem.constraints,
        "examples": problem.examples,
        "starter_code": ensure_starter_code(
            problem.starter_code,
            problem.execution_mode,
            problem.test_cases,
            problem.examples,
        ),
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
    execution_mode: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    candidates = _catalog_rows(db)

    if difficulty:
        requested_difficulty = difficulty.strip().lower()
        candidates = [
            row for row in candidates
            if str(row["difficulty"]).strip().lower() == requested_difficulty
        ]

    if source:
        requested_source = source.strip().lower()
        candidates = [
            row for row in candidates
            if str(row["source"] or "").strip().lower() == requested_source
        ]

    if execution_mode:
        requested_mode = execution_mode.strip().lower()
        candidates = [
            row for row in candidates
            if str(row.get("execution_mode") or "function").strip().lower() == requested_mode
        ]

    if search:
        needle = search.strip().lower()
        candidates = [
            row for row in candidates
            if needle in str(row["title"]).lower()
        ]

    if topic:
        candidates = [
            row for row in candidates
            if _topic_matches(row["topics"], topic)
        ]

    total = len(candidates)
    page = candidates[offset : offset + limit]

    return {
        "items": page,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < total,
    }


@router.get("/topics")
def list_problem_topics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _catalog_rows(db)
    return {
        "total": _catalog_cache["total"],
        "topics": _catalog_cache["topics"],
        "difficulties": _catalog_cache["difficulties"],
    }


@router.get("/taxonomy")
def problem_taxonomy(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _catalog_rows(db)
    active_topics = {item["name"] for item in _catalog_cache["topics"]}
    return {
        "topics": [
            {
                "name": topic,
                "active": topic in active_topics,
                "subtopics": sorted(TOPIC_HIERARCHY.get(topic, {}).get("subtopics", [])),
                "patterns": sorted(TOPIC_HIERARCHY.get(topic, {}).get("patterns", [])),
            }
            for topic in CANONICAL_TOPICS
        ],
        "difficulties": ["Easy", "Medium", "Hard"],
    }


@router.get("/{slug}")
def get_problem(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problem = db.query(Problem).filter(Problem.slug == slug).first()
    if (
        problem is None
        or not is_english_problem(problem.title, problem.description)
        or normalize_difficulty(problem.difficulty) is None
    ):
        raise HTTPException(status_code=404, detail="Problem not found.")
    return serialize(problem)
