from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.database import SessionLocal
from backend.models import Problem
from backend.problem_catalog import audit_problems, invalid_topic_names, normalize_problem_record, quality_flags

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

def import_catalog(path: Path) -> tuple[int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        items = payload.get("problems")
    else:
        items = payload
    if not isinstance(items, list):
        raise ValueError("Catalog JSON must be a list or an object with a 'problems' list.")

    validated_items = []
    created_count = 0
    updated_count = 0
    with SessionLocal() as db:
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"Problem {index} must be an object.")
            item = validate(item, index)
            validated_items.append(item)

            source = item["source"]
            external_id = item.get("external_id")
            slug = str(item["slug"]).strip()
            query = db.query(Problem).filter(Problem.slug == slug)
            if external_id:
                existing = db.query(Problem).filter(
                    Problem.source == source,
                    Problem.external_id == str(external_id),
                ).first()
                if existing is not None:
                    query = db.query(Problem).filter(Problem.id == existing.id)

            problem = query.first()
            values = {
                "slug": slug,
                "title": item["title"],
                "difficulty": item["difficulty"],
                "topics": item["topics"],
                "description": item["description"],
                "constraints": item["constraints"],
                "examples": item["examples"],
                "test_cases": item.get("test_cases", []),
                "starter_code": item["starter_code"],
                "source": source,
                "external_id": str(external_id) if external_id is not None else None,
                "external_url": item.get("external_url"),
                "execution_mode": item.get("execution_mode", "function"),
                "time_limit_ms": item.get("time_limit_ms", 2000),
                "memory_limit_mb": item.get("memory_limit_mb"),
                "validation": item.get("validation", "default"),
                "package_metadata": item.get("package_metadata") or {},
            }
            if problem is None:
                db.add(Problem(**values))
                created_count += 1
            else:
                for key, value in values.items():
                    setattr(problem, key, value)
                updated_count += 1
        duplicate_report = audit_problems(validated_items)
        duplicate_groups = sum(
            len(groups) for groups in duplicate_report["duplicates"].values()
        )
        if duplicate_groups:
            raise ValueError(
                "Catalog contains duplicate problem groups: "
                + json.dumps(duplicate_report["duplicates"], ensure_ascii=False)
            )
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
