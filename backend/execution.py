from __future__ import annotations

import ast
import base64
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any


MAX_CODE_LENGTH = 40_000
TIMEOUT_SECONDS = 2.0
MAX_OUTPUT_LENGTH = 12_000

BLOCKED_IMPORTS = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "http",
    "pathlib",
    "shutil",
    "ctypes",
    "multiprocessing",
    "threading",
    "importlib",
}
BLOCKED_CALLS = {"open", "eval", "exec", "compile", "__import__", "input"}


class CodeRejectedError(ValueError):
    pass


@dataclass
class TestOutcome:
    index: int
    passed: bool
    status: str
    expected: Any | None
    actual: Any | None
    runtime_ms: int
    message: str | None = None


def validate_code(source: str) -> None:
    if len(source) > MAX_CODE_LENGTH:
        raise CodeRejectedError(f"Code exceeds the {MAX_CODE_LENGTH} character limit.")

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CodeRejectedError(
            f"Syntax Error: {exc.msg} (line {exc.lineno})."
        ) from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BLOCKED_IMPORTS:
                    raise CodeRejectedError(f"Import '{root}' is not allowed in the local runner.")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in BLOCKED_IMPORTS:
                raise CodeRejectedError(f"Import '{root}' is not allowed in the local runner.")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                raise CodeRejectedError(f"Call '{node.func.id}' is not allowed in the local runner.")


def _runner_source(user_code: str, args: list[Any]) -> str:
    encoded_code = base64.b64encode(user_code.encode("utf-8")).decode("ascii")
    encoded_args = base64.b64encode(
        json.dumps(args, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    return f"""
import base64
import json

source = base64.b64decode({encoded_code!r}).decode("utf-8")
args = json.loads(base64.b64decode({encoded_args!r}).decode("utf-8"))

namespace = {{}}
exec(compile(source, "<user_code>", "exec"), namespace)

solve = namespace.get("solve")
if not callable(solve):
    raise RuntimeError("Define a callable solve(...) function in your solution.")

result = solve(*args)
print("__CODEMENTOR_RESULT__" + json.dumps(result, separators=(",", ":")))
"""


def _truncate(value: str) -> str:
    return value if len(value) <= MAX_OUTPUT_LENGTH else value[:MAX_OUTPUT_LENGTH] + "\n[output truncated]"


def run_python_tests(source: str, test_cases: list[dict[str, Any]]) -> list[TestOutcome]:
    validate_code(source)

    outcomes: list[TestOutcome] = []

    with tempfile.TemporaryDirectory(prefix="codementor-run-") as workdir:
        script_path = os.path.join(workdir, "runner.py")

        for index, case in enumerate(test_cases, start=1):
            args = case.get("args", [])
            expected = case.get("expected")

            with open(script_path, "w", encoding="utf-8") as script:
                script.write(_runner_source(source, args))

            env = {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PATH": os.environ.get("PATH", ""),
            }

            try:
                completed = subprocess.run(
                    [sys.executable, "-I", script_path],
                    cwd=workdir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Time Limit Exceeded",
                        expected=expected,
                        actual=None,
                        runtime_ms=int(TIMEOUT_SECONDS * 1000),
                        message=f"Test exceeded the {TIMEOUT_SECONDS:.1f}s execution limit.",
                    )
                )
                continue

            stderr = _truncate((completed.stderr or "").strip())
            stdout = _truncate((completed.stdout or "").strip())

            marker = "__CODEMENTOR_RESULT__"
            result_line = next(
                (line for line in stdout.splitlines() if line.startswith(marker)),
                None,
            )

            if completed.returncode != 0:
                message = stderr or stdout or "Program exited with a non-zero status."
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Runtime Error",
                        expected=expected,
                        actual=None,
                        runtime_ms=0,
                        message=message,
                    )
                )
                continue

            if result_line is None:
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Invalid Output",
                        expected=expected,
                        actual=None,
                        runtime_ms=0,
                        message="The solve(...) function did not return a JSON-serializable result.",
                    )
                )
                continue

            try:
                actual = json.loads(result_line[len(marker):])
            except json.JSONDecodeError:
                actual = result_line[len(marker):]

            passed = actual == expected
            outcomes.append(
                TestOutcome(
                    index=index,
                    passed=passed,
                    status="Passed" if passed else "Wrong Answer",
                    expected=expected,
                    actual=actual,
                    runtime_ms=0,
                    message=None if passed else f"Expected {expected!r}, got {actual!r}.",
                )
            )

    return outcomes
