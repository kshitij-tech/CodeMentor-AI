from collections import Counter
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Problem, User
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/problems", tags=["Problems"])


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_VALID_DIFFICULTIES = {"easy", "medium", "hard"}


def _is_english_problem(title: str | None, description: str | None) -> bool:
    text = f"{title or ''}\n{description or ''}"
    return not _CJK_RE.search(text)


def _has_known_difficulty(difficulty: str | None) -> bool:
    return str(difficulty or "").strip().lower() in _VALID_DIFFICULTIES


_TOPIC_ALIASES = {
    "arrays strings": {"array", "arrays", "string", "strings", "arrays strings"},
    "hashing hash maps": {
        "hashing", "hash table", "hash tables", "hash map", "hash maps",
        "map", "maps", "unordered map", "data structures", "hashing hash maps",
    },
    "two pointers": {"two pointer", "two pointers"},
    "binary search": {"binary search"},
    "linked lists": {"linked list", "linked lists"},
    "trees bst": {"tree", "trees", "binary search tree", "bst"},
    "graphs bfs dfs": {
        "graph", "graphs", "bfs", "dfs", "shortest path", "shortest paths", "graphs bfs dfs",
    },
    "dynamic programming": {"dp", "dynamic programming"},
    "backtracking": {"backtracking"},
    "greedy algorithms": {"greedy", "greedy algorithms"},
}


def _normalize_topic(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


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
        )
        .filter(Problem.difficulty.in_({"Easy", "Medium", "Hard", "easy", "medium", "hard"}))
        .order_by(Problem.id.asc())
        .all()
    )

    clean_rows = []
    topic_counts: Counter[str] = Counter()
    difficulty_counts: Counter[str] = Counter()

    for row in rows:
        if not _is_english_problem(row.title, row.description):
            continue
        if not _has_known_difficulty(row.difficulty):
            continue

        item = {
            "id": row.id,
            "slug": row.slug,
            "title": row.title,
            "difficulty": row.difficulty,
            "topics": row.topics or [],
            "source": row.source,
            "external_id": row.external_id,
            "external_url": row.external_url,
        }
        clean_rows.append(item)
        difficulty_counts[str(row.difficulty).strip().title()] += 1

        for topic in row.topics or []:
            topic_text = str(topic).strip()
            if topic_text:
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


def _topic_matches(problem_topics: list[str] | None, requested_topic: str) -> bool:
    requested = _normalize_topic(requested_topic)
    if not requested:
        return True

    aliases = _TOPIC_ALIASES.get(requested, {requested})
    normalized_topics = {_normalize_topic(topic) for topic in (problem_topics or [])}

    if requested in normalized_topics or bool(normalized_topics & aliases):
        return True

    # Also allow the canonical topic to match a more specific imported label.
    for topic in normalized_topics:
        if topic in aliases:
            return True
        for alias in aliases:
            if alias and (alias in topic or topic in alias):
                return True
    return False



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


@router.get("/{slug}")
def get_problem(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problem = db.query(Problem).filter(Problem.slug == slug).first()
    if (
        problem is None
        or not _is_english_problem(problem.title, problem.description)
        or not _has_known_difficulty(problem.difficulty)
    ):
        raise HTTPException(status_code=404, detail="Problem not found.")
    return serialize(problem)
