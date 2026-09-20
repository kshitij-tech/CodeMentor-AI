from __future__ import annotations

import argparse
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from backend.import_problem_package import import_package


SOURCE_REPO = "oj-lab/problem-packages"
SOURCE_URL = "https://github.com/oj-lab/problem-packages/archive/refs/heads/main.zip"


class BulkImportError(RuntimeError):
    pass


def _download_source(destination: Path) -> Path:
    archive_path = destination / "problem-packages.zip"
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "CodeMentor-AI-problem-importer/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            with archive_path.open("wb") as output:
                shutil.copyfileobj(response, output)
    except Exception as exc:
        raise BulkImportError(
            f"Could not download {SOURCE_REPO}: {exc}"
        ) from exc
    return archive_path


def _extract_source(archive_path: Path, destination: Path) -> Path:
    extracted = destination / "source"
    extracted.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            parts = Path(info.filename.replace("\\", "/")).parts
            if any(part == ".." for part in parts) or Path(info.filename).is_absolute():
                raise BulkImportError(f"Unsafe archive member: {info.filename}")

            target = extracted.joinpath(*parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

    roots = [
        path for path in extracted.iterdir()
        if path.is_dir() and (path / "problems").is_dir()
    ]
    if not roots:
        raise BulkImportError("Downloaded source archive does not contain a problems directory.")

    return roots[0] / "problems"


def _discover_packages(problems_root: Path) -> list[Path]:
    packages = []
    for problem_yaml in problems_root.rglob("problem.yaml"):
        package_dir = problem_yaml.parent
        packages.append(package_dir)

    return sorted(packages, key=lambda path: path.relative_to(problems_root).as_posix().lower())


def bulk_import(source_root: Path | None = None) -> tuple[int, int, list[str], list[str]]:
    failures: list[str] = []
    skipped: list[str] = []

    with tempfile.TemporaryDirectory(prefix="codementor-bulk-import-") as temp_dir:
        temp_root = Path(temp_dir)

        if source_root is None:
            archive_path = _download_source(temp_root)
            problems_root = _extract_source(archive_path, temp_root)
        else:
            problems_root = source_root.expanduser().resolve()
            if not problems_root.is_dir():
                raise BulkImportError(f"Source directory does not exist: {problems_root}")

        packages = _discover_packages(problems_root)
        if not packages:
            raise BulkImportError(f"No problem packages found under {problems_root}")

        created = 0
        updated = 0

        for index, package in enumerate(packages, start=1):
            try:
                was_created, summary = import_package(package)
                created += int(was_created)
                updated += int(not was_created)
                status = "created" if was_created else "updated"
                print(
                    f"[{index}/{len(packages)}] {status}: "
                    f"{summary['title']} | "
                    f"{summary['test_cases']} tests | "
                    f"judge-supported={summary['judge_supported']}"
                )
            except Exception as exc:
                if str(exc) == "No English problem statement was found.":
                    skipped.append(str(package))
                    print(f"[{index}/{len(packages)}] SKIPPED (non-English): {package}")
                    continue
                failures.append(f"{package}: {exc}")
                print(f"[{index}/{len(packages)}] FAILED: {package} | {exc}")

    return created, updated, failures, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Import all problem packages from the public MIT-licensed "
            "oj-lab/problem-packages repository."
        )
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="Optional local problems directory instead of downloading the source repository.",
    )
    args = parser.parse_args()

    try:
        created, updated, failures, skipped = bulk_import(args.source_root)
    except BulkImportError as exc:
        raise SystemExit(f"Bulk import failed: {exc}") from exc

    print()
    print(f"Bulk import complete: {created} created, {updated} updated.")
    print(f"Skipped non-English packages: {len(skipped)}")
    print(f"Failed packages: {len(failures)}")

    if skipped:
        for package in skipped:
            print(f" - {package}")

    if failures:
        for failure in failures:
            print(f" - {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
