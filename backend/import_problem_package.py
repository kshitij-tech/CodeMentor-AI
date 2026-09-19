from __future__ import annotations

import argparse
from pathlib import Path

from backend.database import SessionLocal
from backend.models import Problem
from backend.problem_storage import ProblemStorageError, materialize_problem_package
from backend.problem_package import ProblemPackageError, load_problem_package


def _find_existing(db, values: dict):
    if values.get("external_id"):
        existing = (
            db.query(Problem)
            .filter(
                Problem.source == values["source"],
                Problem.external_id == values["external_id"],
            )
            .first()
        )
        if existing is not None:
            return existing

    return db.query(Problem).filter(Problem.slug == values["slug"]).first()


def import_package(path: Path) -> tuple[bool, dict]:
    values = load_problem_package(str(path))

    try:
        package_root = materialize_problem_package(path, values["slug"])
    except ProblemStorageError as exc:
        raise ProblemPackageError(str(exc)) from exc

    values["package_metadata"]["package_root"] = package_root

    with SessionLocal() as db:
        problem = _find_existing(db, values)
        if problem is None:
            db.add(Problem(**values))
            created = True
        else:
            for key, value in values.items():
                setattr(problem, key, value)
            created = False

        db.commit()

        if problem is None:
            problem = (
                db.query(Problem)
                .filter(Problem.slug == values["slug"])
                .first()
            )

        return created, {
            "id": problem.id if problem else None,
            "slug": values["slug"],
            "title": values["title"],
            "test_cases": len(values["test_cases"]),
            "judge_supported": values["package_metadata"]["judge_supported"],
            "time_limit_ms": values["time_limit_ms"],
            "memory_limit_mb": values["memory_limit_mb"],
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import an ICPC/Kattis-compatible problem package into CodeMentor AI."
    )
    parser.add_argument("path", type=Path, help="Problem package directory or .zip file.")
    args = parser.parse_args()

    try:
        created, summary = import_package(args.path)
    except ProblemPackageError as exc:
        raise SystemExit(f"Package import failed: {exc}") from exc

    action = "created" if created else "updated"
    print(
        f"Problem {action}: {summary['title']} ({summary['slug']}) | "
        f"{summary['test_cases']} tests | "
        f"time limit {summary['time_limit_ms']} ms | "
        f"judge-supported={summary['judge_supported']}"
    )


if __name__ == "__main__":
    main()
