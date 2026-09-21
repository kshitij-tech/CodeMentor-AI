from __future__ import annotations

import argparse
import re
from typing import Any

from sqlalchemy import select

from backend.database import SessionLocal
from backend.models import Problem
from backend.problem_catalog import canonicalize_topics


DATASET_NAME = "deepmind/code_contests"

SOURCE_LABELS = [
    "UNKNOWN_SOURCE",
    "CODECHEF",
    "CODEFORCES",
    "HACKEREARTH",
    "CODEJAM",
    "ATCODER",
    "AIZU",
]

DIFFICULTY_LABELS = [
    "UNKNOWN_DIFFICULTY",
    "EASY",
    "MEDIUM",
    "HARD",
    "HARDER",
    "HARDEST",
    "EXTERNAL",
] + list("ABCDEFGHIJKLMNOPQRSTUV")


class CodeContestsImportError(RuntimeError):
    pass


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value[:110] or "code-contest-problem"


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", value))


def _label(value: Any, labels: list[str]) -> str:
    if isinstance(value, int) and 0 <= value < len(labels):
        return labels[value]
    if isinstance(value, str):
        return value
    return labels[0]


def _difficulty(row: dict[str, Any]) -> str:
    rating = int(row.get("cf_rating") or 0)
    if rating > 0:
        if rating < 1200:
            return "Easy"
        if rating < 1800:
            return "Medium"
        return "Hard"

    label = _label(row.get("difficulty"), DIFFICULTY_LABELS)
    if label == "EASY":
        return "Easy"
    if label == "MEDIUM":
        return "Medium"
    if label in {"HARD", "HARDER", "HARDEST"}:
        return "Hard"
    return "Unknown"


def _test_pairs(value: Any, limit: int | None = None) -> list[dict[str, str]]:
    # The dataset can expose nested test data either as a list of records
    # or as {input: [...], output: [...]} depending on the dataset reader.
    pairs: list[dict[str, str]] = []

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                pair = {
                    "input": str(item.get("input") or ""),
                    "output": str(item.get("output") or ""),
                }
                if pair["input"] or pair["output"]:
                    pairs.append(pair)
                    if limit is not None and len(pairs) >= limit:
                        break
        return pairs

    if isinstance(value, dict):
        inputs = value.get("input") or []
        outputs = value.get("output") or []
        if isinstance(inputs, str):
            inputs = [inputs]
        if isinstance(outputs, str):
            outputs = [outputs]

        for index, inp in enumerate(inputs):
            pair = {
                "input": str(inp),
                "output": str(outputs[index]) if index < len(outputs) else "",
            }
            if pair["input"] or pair["output"]:
                pairs.append(pair)
                if limit is not None and len(pairs) >= limit:
                    break

    return pairs


def _time_limit_ms(value: Any) -> int:
    if isinstance(value, dict):
        seconds = int(value.get("seconds") or 0)
        nanos = int(value.get("nanos") or 0)
        total = seconds * 1000 + nanos // 1_000_000
        return max(100, total) if total else 2000
    return 2000


def _memory_limit_mb(value: Any) -> int | None:
    try:
        raw = int(value or 0)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    return max(1, (raw + (1024 * 1024 - 1)) // (1024 * 1024))


def _to_problem(row: dict[str, Any], split: str, max_secret_tests: int) -> dict[str, Any] | None:
    title = str(row.get("name") or "").strip()
    description = str(row.get("description") or "").strip()
    if not title or not description or _contains_cjk(description):
        return None

    input_file = str(row.get("input_file") or "").strip()
    output_file = str(row.get("output_file") or "").strip()
    if input_file or output_file:
        return None

    source_label = _label(row.get("source"), SOURCE_LABELS)
    external_id = str(
        f"cf:{row.get('cf_contest_id')}:{row.get('cf_index')}"
        if row.get("cf_contest_id") and row.get("cf_index")
        else f"{source_label.lower()}:{_slugify(title)}"
    )[:120]

    public = _test_pairs(row.get("public_tests"), limit=8)
    private = _test_pairs(row.get("private_tests"), limit=max_secret_tests)
    remaining = max(0, max_secret_tests - len(private)) if max_secret_tests > 0 else None
    generated = _test_pairs(row.get("generated_tests"), limit=remaining)

    if not public and not private and not generated:
        return None

    samples = [
        {
            "input": item["input"],
            "output": item["output"],
            "name": f"sample-{index + 1}",
        }
        for index, item in enumerate(public[:8])
    ]

    sample_test_cases = [
        {
            "input": item["input"],
            "expected_output": item["output"],
            "visibility": "sample",
            "name": f"sample-{index + 1}",
            "validator_name": None,
            "validator_flags": [],
            "group": "sample",
        }
        for index, item in enumerate(public[:8])
    ]

    secret_pool = private + generated

    test_cases = sample_test_cases + [
        {
            "input": item["input"],
            "expected_output": item["output"],
            "visibility": "secret",
            "name": f"secret-{index + 1}",
            "validator_name": None,
            "validator_flags": [],
            "group": "secret",
        }
        for index, item in enumerate(secret_pool)
    ]

    if not test_cases:
        return None

    cf_url = None
    if row.get("cf_contest_id") and row.get("cf_index"):
        cf_url = (
            f"https://codeforces.com/problemset/problem/"
            f"{row['cf_contest_id']}/{row['cf_index']}"
        )

    tags = row.get("cf_tags") or []
    topics = canonicalize_topics(tags)

    source_name = source_label.lower().replace("_", "-")
    package_metadata = {
        "dataset": DATASET_NAME,
        "dataset_split": split,
        "dataset_license": "CC BY 4.0",
        "source_label": source_label,
        "cf_contest_id": row.get("cf_contest_id"),
        "cf_index": row.get("cf_index"),
        "cf_points": row.get("cf_points"),
        "cf_rating": row.get("cf_rating"),
        "translated_description": bool(row.get("is_description_translated")),
        "test_case_count": len(test_cases),
        "sample_test_count": len(samples),
        "secret_test_count": len(test_cases) - len(samples),
    }

    return {
        "slug": _slugify(f"{source_name}-{title}"),
        "title": title[:180],
        "difficulty": _difficulty(row),
        "topics": topics,
        "description": description,
        "constraints": [],
        "examples": samples,
        "test_cases": test_cases,
        "starter_code": {
            "Python": (
                "import sys\n\n"
                "def solve():\n"
                "    # Read from standard input and write the required answer.\n"
                "    pass\n\n"
                "if __name__ == '__main__':\n"
                "    solve()\n"
            )
        },
        "source": f"code-contests-{source_name}"[:40],
        "external_id": external_id,
        "external_url": cf_url,
        "execution_mode": "stdio",
        "time_limit_ms": _time_limit_ms(row.get("time_limit")),
        "memory_limit_mb": _memory_limit_mb(row.get("memory_limit_bytes")),
        "validation": "default",
        "package_metadata": package_metadata,
    }


def bulk_import(
    *,
    split: str,
    max_problems: int,
    max_secret_tests: int,
    batch_size: int,
) -> tuple[int, int, int]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise CodeContestsImportError(
            "The optional importer dependency is missing. "
            "Run: pip install -r backend/requirements-problem-import.txt"
        ) from exc

    try:
        dataset = load_dataset(DATASET_NAME, split=split, streaming=True)
    except Exception as exc:
        raise CodeContestsImportError(
            f"Could not open {DATASET_NAME}:{split}: {exc}"
        ) from exc

    created = 0
    updated = 0
    skipped = 0
    processed = 0

    with SessionLocal() as db:
        for row in dataset:
            if max_problems > 0 and processed >= max_problems:
                break

            problem = _to_problem(row, split, max_secret_tests)
            if problem is None:
                skipped += 1
                continue

            existing = db.execute(
                select(Problem).where(
                    Problem.source == problem["source"],
                    Problem.external_id == problem["external_id"],
                )
            ).scalar_one_or_none()

            if existing is None:
                db.add(Problem(**problem))
                created += 1
            else:
                for key, value in problem.items():
                    setattr(existing, key, value)
                updated += 1

            processed += 1

            if processed % batch_size == 0:
                db.commit()
                print(
                    f"Imported {processed} | created={created} "
                    f"updated={updated} skipped={skipped}"
                )

        db.commit()

    return created, updated, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream English competitive-programming problems from DeepMind CodeContests."
    )
    parser.add_argument("--split", default="all", choices=["all", "train", "valid", "test"])
    parser.add_argument(
        "--max-problems",
        type=int,
        default=0,
        help="Maximum problems to import; 0 means all available problems.",
    )
    parser.add_argument(
        "--max-secret-tests",
        type=int,
        default=10,
        help="Maximum private/generated tests stored per problem; 0 means all.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Commit after this many problems to keep SQLite writes small.",
    )
    args = parser.parse_args()

    splits = ["train", "valid", "test"] if args.split == "all" else [args.split]
    total_created = 0
    total_updated = 0
    total_skipped = 0

    for split in splits:
        created, updated, skipped = bulk_import(
            split=split,
            max_problems=args.max_problems,
            max_secret_tests=args.max_secret_tests,
            batch_size=max(1, args.batch_size),
        )
        total_created += created
        total_updated += updated
        total_skipped += skipped
        print(
            f"{split}: {created} created, {updated} updated, {skipped} skipped."
        )

    print()
    print(
        f"CodeContests import complete: {total_created} created, "
        f"{total_updated} updated, {total_skipped} skipped."
    )


if __name__ == "__main__":
    try:
        main()
    except CodeContestsImportError as exc:
        raise SystemExit(f"CodeContests import failed: {exc}") from exc
