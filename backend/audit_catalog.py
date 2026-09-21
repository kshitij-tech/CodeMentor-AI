from __future__ import annotations

import argparse
import json
from collections import defaultdict

from backend.database import SessionLocal
from backend.models import Problem
from backend.problem_catalog import audit_problems


def load_problem_records() -> list[dict]:
    with SessionLocal() as db:
        rows = db.query(Problem).order_by(Problem.id.asc()).all()
        return [
            {
                "id": row.id,
                "slug": row.slug,
                "title": row.title,
                "difficulty": row.difficulty,
                "topics": row.topics or [],
                "description": row.description,
                "constraints": row.constraints or [],
                "examples": row.examples or [],
                "test_cases": row.test_cases or [],
                "starter_code": row.starter_code or {},
                "source": row.source,
                "external_id": row.external_id,
                "external_url": row.external_url,
            }
            for row in rows
        ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit the local CodeMentor AI problem catalogue."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of the human-readable report.",
    )
    parser.add_argument(
        "--fail-on-issues",
        action="store_true",
        help="Return exit code 1 when any catalogue issue is found.",
    )
    args = parser.parse_args()

    report = audit_problems(load_problem_records())

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("CodeMentor AI — Problem Catalogue Audit")
        print("=" * 44)
        print(f"Total problems : {report['total']}")
        print(f"Clean problems : {report['clean']}")
        print(f"Problems with issues : {report['total'] - report['clean']}")
        print()

        issues = report["issues"]
        if not issues:
            print("No catalogue quality issues detected.")
        else:
            print("Issue counts")
            print("-" * 44)
            for name, count in issues.items():
                print(f"{name:28} {count}")

        duplicates = report["duplicates"]
        duplicate_groups = [
            (kind, labels)
            for kind, groups in duplicates.items()
            for labels in groups.values()
        ]
        print()
        print(f"Duplicate groups : {len(duplicate_groups)}")
        for index, (kind, labels) in enumerate(duplicate_groups, start=1):
            print(f"  {index}. [{kind}] {', '.join(labels)}")

    return 1 if args.fail_on_issues and (
        report["issues"] or report["duplicates"]
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
