
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
TEST_DIR = ROOT / "backend" / "tests"
QA_TEST_FILES = [
    str(path.relative_to(ROOT))
    for path in sorted(TEST_DIR.glob("test_qa_*.py"))
]
QA_SOURCES = ["backend/tests/qa_support.py", *QA_TEST_FILES, "qa/quality_gate.py"]


def run(command: list[str], *, allow_missing: bool = False) -> bool:
    executable = shutil.which(command[0]) if command else None
    if command and executable is None:
        if allow_missing:
            print(f"[quality-gate] optional tool not installed: {command[0]}")
            return True
        print(f"[quality-gate] required tool not installed: {command[0]}")
        return False

    print("[quality-gate] " + " ".join(command))
    result = subprocess.run(command, cwd=ROOT, check=False)
    return result.returncode == 0


def main() -> int:
    checks: list[tuple[str, bool]] = []

    coverage_available = shutil.which("coverage") is not None
    if coverage_available:
        checks.append(
            (
                "coverage unittest",
                run(
                    [
                        "coverage",
                        "run",
                        "--branch",
                        "-m",
                        "unittest",
                        "discover",
                        "-s",
                        str(TEST_DIR),
                        "-p",
                        "test_*.py",
                    ]
                ),
            )
        )
        checks.append(
            (
                "coverage report",
                run(["coverage", "report", "-m", "--fail-under=50"]),
            )
        )
        checks.append(
            (
                "coverage xml",
                run(["coverage", "xml", "-o", str(ROOT / "coverage.xml")]),
            )
        )
    else:
        checks.append(
            (
                "unittest fallback",
                run(
                    [
                        PYTHON,
                        "-m",
                        "unittest",
                        "discover",
                        "-s",
                        str(TEST_DIR),
                        "-p",
                        "test_*.py",
                    ]
                ),
            )
        )

    checks.append(
        (
            "compileall",
            run([PYTHON, "-m", "compileall", "-q", "backend", "qa"]),
        )
    )

    checks.append(
        (
            "ruff check",
            run(["ruff", "check", *QA_SOURCES], allow_missing=True),
        )
    )
    checks.append(
        (
            "ruff format",
            run(
                ["ruff", "format", "--check", *QA_SOURCES],
                allow_missing=True,
            ),
        )
    )
    checks.append(
        (
            "mypy QA suite",
            run(
                ["mypy", "--ignore-missing-imports", *QA_SOURCES],
                allow_missing=True,
            ),
        )
    )

    failed = [name for name, ok in checks if not ok]
    if failed:
        print("[quality-gate] failed: " + ", ".join(failed))
        return 1

    print("[quality-gate] all quality checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
