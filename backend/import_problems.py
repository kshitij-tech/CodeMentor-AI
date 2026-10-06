from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterator

from backend.database import SessionLocal
from backend.models import Problem
from backend.problem_catalog import _content_fingerprint, invalid_topic_names, normalize_problem_record, quality_flags

REQUIRED = {
    "slug", "title", "difficulty", "topics", "description",
    "constraints", "examples", "test_cases", "starter_code",
}

def validate(item: dict, index: int) -> dict:
    missing = REQUIRED - set(item)
    if missing:
        raise ValueError(f"Problem {index} is missing: {', '.join(sorted(missing))}")

    bad_topics = invalid_topic_names(item.get("topics"))
    if bad_topics:
        raise ValueError(
            f"Problem {index} has invalid topic names: {', '.join(bad_topics)}"
        )

    normalized = normalize_problem_record(item)

    if not isinstance(normalized["topics"], list):
        raise ValueError(f"Problem {index}: topics must be a list")
    if not isinstance(normalized.get("constraints"), list):
        raise ValueError(f"Problem {index}: constraints must be a list")
    if not isinstance(normalized.get("examples"), list):
        raise ValueError(f"Problem {index}: examples must be a list")
    if not isinstance(normalized.get("starter_code"), dict):
        raise ValueError(f"Problem {index}: starter_code must be an object")
    if not isinstance(normalized.get("test_cases", []), list):
        raise ValueError(f"Problem {index}: test_cases must be a list")

    flags = quality_flags(normalized)
    if flags:
        raise ValueError(
            f"Problem {index} failed catalogue quality checks: {', '.join(flags)}"
        )

    return normalized

def _iter_items(path: Path) -> Iterator[dict]:
    try:
        import ijson
    except ImportError:
        ijson = None
    if ijson is None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("problems") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("Catalog JSON must be a list or an object with a 'problems' list.")
        yield from items
        return
    with path.open("rb") as handle:
        first = handle.read(1)
        while first and first.isspace():
            first = handle.read(1)
        if first == b"[":
            handle.seek(0)
            yield from ijson.items(handle, "item")
        elif first == b"{":
            handle.seek(0)
            yield from ijson.items(handle, "problems.item")
        else:
            raise ValueError("Catalog JSON must start with '[' or '{'.")

def _preflight_catalog(path: Path) -> int:
    seen_slugs: dict[str, int] = {}
    seen_external: dict[tuple[str, str], int] = {}
    seen_content: dict[str, int] = {}
    total = 0
    for index, raw in enumerate(_iter_items(path), start=1):
        normalized = validate(raw, index)
        slug = normalized["slug"]
        if slug in seen_slugs:
            raise ValueError(f"Problem {index}: duplicate slug '{slug}' also appears at problem {seen_slugs[slug]}.")
        seen_slugs[slug] = index
        source = str(normalized.get("source") or "").strip().lower()
        external_id = str(normalized.get("external_id") or "").strip().lower()
        if source and external_id:
            identity = (source, external_id)
            if identity in seen_external:
                raise ValueError(f"Problem {index}: duplicate source/external-id matches problem {seen_external[identity]}.")
            seen_external[identity] = index
        key = _content_fingerprint(normalized)
        if key in seen_content:
            raise ValueError(f"Problem {index}: duplicate content matches problem {seen_content[key]}.")
        seen_content[key] = index
        total += 1
    if total == 0:
        raise ValueError("Catalog must contain at least one problem.")
    return total

def import_catalog(path: Path) -> tuple[int, int]:
    total = _preflight_catalog(path)
    created_count = 0
    updated_count = 0
    with SessionLocal() as db:
        by_slug = {row.slug: row.id for row in db.query(Problem.id, Problem.slug).yield_per(1000)}
        by_identity: dict[tuple[str, str], int] = {}
        by_content: dict[str, int] = {}
        for row in db.query(Problem.id, Problem.source, Problem.external_id, Problem.title, Problem.description).yield_per(1000):
            if row.source and row.external_id:
                by_identity[(str(row.source).strip().lower(), str(row.external_id).strip().lower())] = row.id
            by_content[_content_fingerprint({"title": row.title, "description": row.description})] = row.id
        for index, raw in enumerate(_iter_items(path), start=1):
            item = validate(raw, index)
            source = str(item["source"]).strip()
            external_id = str(item.get("external_id") or "").strip()
            identity = (source.lower(), external_id.lower()) if external_id else None
            existing_id = by_identity.get(identity) if identity else None
            if existing_id is None:
                existing_id = by_slug.get(item["slug"])
            content_id = by_content.get(_content_fingerprint(item))
            if content_id is not None and content_id != existing_id:
                raise ValueError(f"Problem {index}: duplicate content matches existing catalogue problem id {content_id}.")
            values = {
                "slug": item["slug"], "title": item["title"], "difficulty": item["difficulty"],
                "topics": item["topics"], "description": item["description"], "constraints": item["constraints"],
                "examples": item["examples"], "test_cases": item.get("test_cases", []),
                "starter_code": item["starter_code"], "source": source,
                "external_id": external_id or None, "external_url": item.get("external_url"),
                "execution_mode": item.get("execution_mode", "function"),
                "time_limit_ms": item.get("time_limit_ms", 2000),
                "memory_limit_mb": item.get("memory_limit_mb"),
                "validation": item.get("validation", "default"),
                "package_metadata": item.get("package_metadata") or {},
            }
            if existing_id is None:
                problem = Problem(**values)
                db.add(problem)
                db.flush()
                existing_id = problem.id
                created_count += 1
            else:
                problem = db.get(Problem, existing_id)
                if problem is None:
                    raise ValueError(f"Problem {index}: existing problem {existing_id} was not found.")
                for key, value in values.items():
                    setattr(problem, key, value)
                updated_count += 1
            by_slug[item["slug"]] = existing_id
            if identity:
                by_identity[identity] = existing_id
            by_content[_content_fingerprint(item)] = existing_id
        if created_count + updated_count != total:
            raise RuntimeError(f"Import count mismatch: expected {total}, got {created_count + updated_count}")
        db.commit()
    return created_count, updated_count

def main() -> None:
    parser = argparse.ArgumentParser(description="Import an authorized CodeMentor problem catalog JSON file.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    created, updated = import_catalog(args.path)
    print(f"Imported catalog: {created} created, {updated} updated.")

if __name__ == "__main__":
    main()
