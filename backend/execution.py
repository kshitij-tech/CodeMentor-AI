from __future__ import annotations

from backend.custom_validator import CustomValidatorError, run_custom_validator
from backend.validator import UnsupportedValidatorError, validate_default_output

import ast
import base64
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Any


MAX_CODE_LENGTH = 40_000
TIMEOUT_SECONDS = 2.0
MAX_TIMEOUT_SECONDS = 10.0
MAX_COMPILE_SECONDS = 10.0
MAX_MEMORY_MB = 1024
MAX_OUTPUT_LENGTH = 12_000

LANGUAGE_EXTENSIONS = {
    "Python": ".py",
    "C++": ".cpp",
    "Java": ".java",
    "JavaScript": ".js",
    "TypeScript": ".ts",
    "Go": ".go",
    "Rust": ".rs",
}

COMPILED_LANGUAGES = {"C++", "Java", "TypeScript", "Go", "Rust"}

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


def syntax_diagnostic(source: str) -> dict[str, object]:
    """Return a JSON-safe syntax diagnostic without executing user code."""
    if len(source) > MAX_CODE_LENGTH:
        return {
            "valid": False,
            "message": f"Code exceeds the {MAX_CODE_LENGTH} character limit.",
            "line": 1,
            "column": 1,
            "end_line": 1,
            "end_column": 2,
        }

    try:
        ast.parse(source)
    except SyntaxError as exc:
        line = max(1, int(exc.lineno or 1))
        column = max(1, int(exc.offset or 1))
        end_line = max(line, int(getattr(exc, "end_lineno", None) or line))
        end_offset = getattr(exc, "end_offset", None)
        end_column = max(
            column + 1,
            int(end_offset) if end_offset is not None else column + 1,
        )

        # Python sometimes points at a single character for an invalid token
        # and sometimes only gives a caret position. Expand to the nearest
        # token so Monaco visibly marks the offending word/token.
        source_lines = source.splitlines()
        if 1 <= line <= len(source_lines):
            line_text = source_lines[line - 1]
            if end_line == line:
                start_index = min(len(line_text), column - 1)
                end_index = min(len(line_text), max(start_index + 1, end_column - 1))
                if start_index < len(line_text):
                    if line_text[start_index].isspace():
                        left = start_index
                        while left > 0 and not line_text[left - 1].isspace():
                            left -= 1
                        right = start_index
                        while right < len(line_text) and not line_text[right].isspace():
                            right += 1
                        if left != right:
                            column = left + 1
                            end_column = right + 1

        return {
            "valid": False,
            "message": exc.msg or "Syntax error.",
            "line": line,
            "column": column,
            "end_line": end_line,
            "end_column": end_column,
        }

    return {
        "valid": True,
        "message": None,
        "line": None,
        "column": None,
        "end_line": None,
        "end_column": None,
    }


EXECUTION_SANDBOX = os.getenv("EXECUTION_SANDBOX", "local").strip().lower()
EXECUTION_DOCKER_IMAGE = os.getenv(
    "EXECUTION_DOCKER_IMAGE",
    "codementor-multi-runtime:latest",
).strip()
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
PRODUCTION_ENVS = {"prod", "production"}


def _sandbox_mode() -> str:
    if EXECUTION_SANDBOX not in {"local", "docker"}:
        raise CodeRejectedError(
            "Invalid EXECUTION_SANDBOX. Use 'docker' or 'local'."
        )

    if APP_ENV in PRODUCTION_ENVS and EXECUTION_SANDBOX != "docker":
        raise CodeRejectedError(
            "Production execution requires EXECUTION_SANDBOX=docker."
        )

    if EXECUTION_SANDBOX == "docker" and not shutil.which("docker"):
        raise CodeRejectedError(
            "Docker execution is enabled, but the Docker CLI was not found."
        )

    return EXECUTION_SANDBOX


def _docker_base_command(
    workdir: str,
    *,
    memory_limit_mb: int | None,
    docker_name: str,
) -> list[str]:
    mounted_workdir = os.path.abspath(workdir)
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        docker_name,
        "--network",
        "none",
        "--cpus",
        "1",
        "--memory",
        f"{memory_limit_mb or 256}m",
        "--pids-limit",
        "64",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--tmpfs",
        "/runner:rw,nosuid,size=64m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65532:65532",
        "-v",
        f"{mounted_workdir}:/workspace:ro",
        "-w",
        "/workspace",
    ]


def _run_python_process(
    script_path: str,
    workdir: str,
    *,
    input_data: str | None,
    timeout_seconds: float,
    memory_limit_mb: int | None = None,
    env: dict[str, str] | None,
):
    mode = _sandbox_mode()
    timeout_seconds = min(MAX_TIMEOUT_SECONDS, max(0.1, float(timeout_seconds)))
    memory_limit = (
        None
        if memory_limit_mb is None
        else min(MAX_MEMORY_MB, max(64, int(memory_limit_mb)))
    )
    docker_name = None

    if mode == "local":
        creationflags = 0
        start_new_session = False
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            start_new_session = True

        command = [sys.executable, "-I", "-B", script_path]
        process = subprocess.Popen(
            command,
            cwd=workdir,
            env=env,
            stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        try:
            stdout, stderr = process.communicate(
                input=input_data,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

            stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(
                command,
                timeout_seconds,
                output=stdout,
                stderr=stderr,
            ) from exc

        return subprocess.CompletedProcess(
            command,
            process.returncode,
            stdout,
            stderr,
        )

    docker_name = f"codementor-run-{uuid.uuid4().hex[:16]}"
    script_name = os.path.basename(script_path)
    command = _docker_base_command(
        workdir,
        memory_limit_mb=memory_limit,
        docker_name=docker_name,
    ) + [
        EXECUTION_DOCKER_IMAGE,
        "python",
        "-I",
        "-B",
        f"/workspace/{script_name}",
    ]

    try:
        return subprocess.run(
            command,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["docker", "rm", "-f", docker_name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        raise


def _language_commands(
    language: str,
    source_path: str,
    workdir: str,
) -> tuple[list[str] | None, list[str], list[str] | None]:
    """Return compile command, run command, and Docker shell command pieces."""
    source_name = os.path.basename(source_path)
    if language == "Python":
        return None, [sys.executable, "-I", "-B", source_path], None
    if language == "C++":
        return [
            "g++", "-std=c++20", "-O2", "-pipe", "-s",
            source_path, "-o", os.path.join(workdir, "codementor_program"),
        ], [os.path.join(workdir, "codementor_program")], [
            "g++ -std=c++20 -O2 -pipe -s /workspace/"+source_name+" -o /runner/codementor_program && echo __CODEMENTOR_COMPILE_OK__ && /runner/codementor_program"
        ]
    if language == "Java":
        return [
            "javac", "-encoding", "UTF-8", "-d", workdir, source_path
        ], ["java", "-cp", workdir, "Main"], [
            "mkdir -p /runner/classes && javac -encoding UTF-8 -d /runner/classes /workspace/"+source_name+" && echo __CODEMENTOR_COMPILE_OK__ && java -cp /runner/classes Main"
        ]
    if language == "JavaScript":
        return None, ["node", "--use-strict", source_path], None
    if language == "TypeScript":
        return [
            "tsc", "--target", "ES2022", "--module", "commonjs",
            "--strict", "false", "--outDir", os.path.join(workdir, "tsc"),
            source_path,
        ], ["node", os.path.join(workdir, "tsc", "solution.js")], [
            "mkdir -p /runner/tsc && tsc --target ES2022 --module commonjs --strict false --outDir /runner/tsc /workspace/"+source_name+" && echo __CODEMENTOR_COMPILE_OK__ && node /runner/tsc/"+os.path.splitext(source_name)[0]+".js"
        ]
    if language == "Go":
        return [
            "go", "build", "-o", os.path.join(workdir, "codementor_program"), source_path
        ], [os.path.join(workdir, "codementor_program")], [
            "GOCACHE=/tmp/go-cache go build -o /runner/codementor_program /workspace/"+source_name+" && echo __CODEMENTOR_COMPILE_OK__ && /runner/codementor_program"
        ]
    if language == "Rust":
        return [
            "rustc", "-O", source_path, "-o", os.path.join(workdir, "codementor_program")
        ], [os.path.join(workdir, "codementor_program")], [
            "rustc -O /workspace/"+source_name+" -o /runner/codementor_program && echo __CODEMENTOR_COMPILE_OK__ && /runner/codementor_program"
        ]
    raise CodeRejectedError(f"Unsupported language runtime: {language}.")


def _docker_language_script(
    language: str,
    source_name: str,
    test_cases: list[dict[str, Any]],
    time_limit_seconds: float,
    token: str,
) -> str:
    run_commands = {
        "C++": "/runner/codementor_program",
        "Java": "java -cp /runner/classes Main",
        "JavaScript": "node --use-strict /workspace/solution.js",
        "TypeScript": "node /runner/tsc/solution.js",
        "Go": "/runner/codementor_program",
        "Rust": "/runner/codementor_program",
    }
    compile_commands = {
        "C++": (
            "g++ -std=c++20 -O2 -pipe -s "
            f"/workspace/{source_name} -o /runner/codementor_program"
        ),
        "Java": (
            "mkdir -p /runner/classes && "
            f"javac -encoding UTF-8 -d /runner/classes /workspace/{source_name}"
        ),
        "TypeScript": (
            "mkdir -p /runner/tsc && "
            f"tsc --target ES2022 --module commonjs --strict false "
            f"--outDir /runner/tsc /workspace/{source_name}"
        ),
        "Go": (
            "GOCACHE=/tmp/go-cache "
            f"go build -o /runner/codementor_program /workspace/{source_name}"
        ),
        "Rust": (
            f"rustc -O /workspace/{source_name} -o /runner/codementor_program"
        ),
    }

    lines = [
        "set -o pipefail",
        f"COMPILE_MARKER='__CODEMENTOR_{token}_COMPILE_OK__'",
    ]

    if language in compile_commands:
        lines.append(compile_commands[language])
        lines.append("compile_rc=$?")
        lines.append('if [ "$compile_rc" -ne 0 ]; then exit "$compile_rc"; fi')
        lines.append('printf "%s\\n" "$COMPILE_MARKER"')

    run_command = run_commands[language]
    limit = f"{min(MAX_TIMEOUT_SECONDS, max(0.1, float(time_limit_seconds))):.3f}s"

    for index, case in enumerate(test_cases, start=1):
        input_b64 = base64.b64encode(
            str(case.get("input", "")).encode("utf-8")
        ).decode("ascii")
        stdout_marker = f"__CODEMENTOR_{token}_TEST_{index}__"
        stderr_path = f"/runner/stderr_{index}.txt"
        lines.extend([
            f"INPUT_B64='{input_b64}'",
            f"STDERR_PATH='{stderr_path}'",
            ': > "$STDERR_PATH"',
            (
                f'OUTPUT_B64="$(printf "%s" "$INPUT_B64" | base64 -d | '
                f'timeout --signal=KILL {limit} {run_command} '
                f'2>"$STDERR_PATH" | base64 -w0)"'
            ),
            "RC=$?",
            'ERROR_B64="$(base64 -w0 "$STDERR_PATH" 2>/dev/null || true)"',
            (
                f'printf "%s|%s|%s|%s\\n" '
                f"'{stdout_marker}' "$RC" "$OUTPUT_B64" "$ERROR_B64""
            ),
        ])

    return "\n".join(lines) + "\n"


def _decode_b64(value: str) -> str:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True).decode(
            "utf-8",
            errors="replace",
        )
    except (ValueError, UnicodeError):
        return ""


def run_language_stdio_tests(
    source: str,
    language: str,
    test_cases: list[dict[str, Any]],
    time_limit_seconds: float = 2.0,
    *,
    memory_limit_mb: int | None = None,
) -> list[TestOutcome]:
    if language not in LANGUAGE_EXTENSIONS:
        raise CodeRejectedError(f"Unsupported language runtime: {language}.")

    if len(source) > MAX_CODE_LENGTH:
        raise CodeRejectedError(f"Code exceeds the {MAX_CODE_LENGTH} character limit.")

    if language != "Python" and _sandbox_mode() != "docker":
        raise CodeRejectedError(
            "Docker sandbox is required for non-Python execution. "
            "Set EXECUTION_SANDBOX=docker and restart FastAPI."
        )

    outcomes: list[TestOutcome] = []
    extension = LANGUAGE_EXTENSIONS[language]
    file_name = "Main.java" if language == "Java" else "solution"+extension

    with tempfile.TemporaryDirectory(prefix="codementor-lang-") as workdir:
        source_path = os.path.join(workdir, file_name)
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write(source)

        token = uuid.uuid4().hex[:16]
        script_path = os.path.join(workdir, "run_tests.sh")
        script = _docker_language_script(
            language,
            file_name,
            test_cases,
            time_limit_seconds,
            token,
        )
        with open(script_path, "w", encoding="utf-8") as script_file:
            script_file.write(script)

        docker_name = f"codementor-run-{uuid.uuid4().hex[:16]}"
        docker_cmd = _docker_base_command(
            workdir,
            memory_limit_mb=memory_limit_mb,
            docker_name=docker_name,
        ) + [
            EXECUTION_DOCKER_IMAGE,
            "/bin/bash",
            "/workspace/run_tests.sh",
        ]

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                docker_cmd,
                input=None,
                capture_output=True,
                text=True,
                timeout=min(MAX_TIMEOUT_SECONDS * max(1, len(test_cases)), 120.0),
                check=False,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["docker", "rm", "-f", docker_name],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return [
                TestOutcome(
                    index=index,
                    passed=False,
                    status="Time Limit Exceeded",
                    expected=str(case.get("expected_output", "")),
                    actual=None,
                    runtime_ms=int(MAX_TIMEOUT_SECONDS * 1000),
                    message="The execution container exceeded the overall safety limit.",
                )
                for index, case in enumerate(test_cases, start=1)
            ]

        total_runtime_ms = int((time.perf_counter() - started) * 1000)
        stdout = completed.stdout or ""
        stderr = _truncate((completed.stderr or "").strip())
        lines = stdout.splitlines()

        compile_marker = f"__CODEMENTOR_{token}_COMPILE_OK__"
        if language in COMPILED_LANGUAGES and compile_marker not in lines:
            message = stderr or stdout.strip() or "Compilation failed."
            return [
                TestOutcome(
                    index=1,
                    passed=False,
                    status="Compile Error",
                    expected=str(test_cases[0].get("expected_output", "")) if test_cases else "",
                    actual=None,
                    runtime_ms=total_runtime_ms,
                    message=message,
                )
            ]

        parsed: dict[int, tuple[int, str, str]] = {}
        pattern = re.compile(
            rf"^__CODEMENTOR_{re.escape(token)}_TEST_(\d+)__\|(-?\d+)\|([^|]*)\|([^|]*)$"
        )
        for line in lines:
            match = pattern.match(line)
            if not match:
                continue
            parsed[int(match.group(1))] = (
                int(match.group(2)),
                _decode_b64(match.group(3)),
                _decode_b64(match.group(4)),
            )

        per_test_cap_ms = int(
            min(MAX_TIMEOUT_SECONDS, max(0.1, float(time_limit_seconds))) * 1000
        )
        for index, case in enumerate(test_cases, start=1):
            expected = str(case.get("expected_output", ""))
            item = parsed.get(index)
            if item is None:
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Runtime Error",
                        expected=expected,
                        actual=None,
                        runtime_ms=per_test_cap_ms,
                        message=(
                            "The sandbox did not return a result for this test case."
                        ),
                    )
                )
                continue

            rc, actual, error_text = item
            if rc == 124:
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Time Limit Exceeded",
                        expected=expected,
                        actual=None,
                        runtime_ms=per_test_cap_ms,
                        message=(
                            f"Test exceeded the "
                            f"{min(MAX_TIMEOUT_SECONDS, max(0.1, float(time_limit_seconds))):.2f}s "
                            "execution limit."
                        ),
                    )
                )
                continue

            if rc != 0:
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Runtime Error",
                        expected=expected,
                        actual=actual,
                        runtime_ms=per_test_cap_ms,
                        message=error_text or f"Program exited with status {rc}.",
                    )
                )
                continue

            if len(actual) > MAX_OUTPUT_LENGTH:
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Output Limit Exceeded",
                        expected=expected,
                        actual=_truncate(actual),
                        runtime_ms=per_test_cap_ms,
                        message=f"Program output exceeded {MAX_OUTPUT_LENGTH} characters.",
                    )
                )
                continue

            try:
                validation = validate_default_output(
                    actual,
                    expected,
                    case.get("validator_flags"),
                )
            except UnsupportedValidatorError as exc:
                raise CodeRejectedError(str(exc)) from exc

            outcomes.append(
                TestOutcome(
                    index=index,
                    passed=validation.passed,
                    status="Passed" if validation.passed else "Wrong Answer",
                    expected=expected,
                    actual=actual,
                    runtime_ms=per_test_cap_ms,
                    message=None if validation.passed else validation.message,
                )
            )

    return outcomes


@dataclass
class TestOutcome:
    index: int
    passed: bool
    status: str
    expected: Any | None
    actual: Any | None
    runtime_ms: int
    message: str | None = None


def validate_code(source: str, *, stdio: bool = False) -> None:
    if len(source) > MAX_CODE_LENGTH:
        raise CodeRejectedError(f"Code exceeds the {MAX_CODE_LENGTH} character limit.")

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CodeRejectedError(
            f"Syntax Error: {exc.msg} (line {exc.lineno})."
        ) from exc

    blocked_imports = set(BLOCKED_IMPORTS)
    blocked_calls = set(BLOCKED_CALLS)
    if stdio:
        # Standard contest programs commonly use sys.stdin/stdout and input().
        blocked_imports.discard("sys")
        blocked_calls.discard("input")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in blocked_imports:
                    raise CodeRejectedError(f"Import '{root}' is not allowed in the local runner.")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in blocked_imports:
                raise CodeRejectedError(f"Import '{root}' is not allowed in the local runner.")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in blocked_calls:
                raise CodeRejectedError(f"Call '{node.func.id}' is not allowed in the local runner.")


def extract_error_location(message: str | None) -> tuple[int, int | None] | None:
    if not message:
        return None

    patterns = [
        (
            r'(?:Main\\.java|solution\\.[A-Za-z0-9]+)\\((\\d+),(\\d+)\\)',
            True,
        ),
        (
            r'(?:Main\\.java|solution\\.[A-Za-z0-9]+):(\\d+)(?::(\\d+))?',
            True,
        ),
        (
            r'<user_code>["\\']?,\\s*line\\s+(\\d+)',
            False,
        ),
        (
            r'<user_code>.*?line\\s+(\\d+)',
            False,
        ),
        (
            r'line\\s+(\\d+)\\b',
            False,
        ),
    ]

    for pattern, has_column in patterns:
        match = re.search(pattern, message)
        if not match:
            continue
        if has_column:
            line = int(match.group(1))
            column = int(match.group(2)) if match.group(2) else None
            return line, column
        return int(match.group(1)), None

    return None


def extract_error_line(message: str | None) -> int | None:
    location = extract_error_location(message)
    return location[0] if location else None


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




def _normalize_output(value: str) -> str:
    return " ".join(value.strip().split())


def run_python_stdio_tests(
    source: str,
    test_cases: list[dict[str, Any]],
    time_limit_seconds: float = 2.0,
    *,
    memory_limit_mb: int | None = None,
    package_root: str | None = None,
    validation_time_seconds: float = 60.0,
    validation_output_bytes: int = 8 * 1024 * 1024,
) -> list[TestOutcome]:
    validate_code(source, stdio=True)
    outcomes: list[TestOutcome] = []

    with tempfile.TemporaryDirectory(prefix="codementor-stdio-") as workdir:
        script_path = os.path.join(workdir, "solution.py")
        with open(script_path, "w", encoding="utf-8") as script:
            script.write(source)

        env = {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": os.environ.get("PATH", ""),
        }

        for index, case in enumerate(test_cases, start=1):
            input_data = str(case.get("input", ""))
            expected = str(case.get("expected_output", ""))
            started = time.perf_counter()

            try:
                completed = _run_python_process(
                    script_path,
                    workdir,
                    input_data=input_data,
                    timeout_seconds=min(
                        MAX_TIMEOUT_SECONDS,
                        max(0.1, float(time_limit_seconds)),
                    ),
                    memory_limit_mb=memory_limit_mb,
                    env=env,
                )
                runtime_ms = int((time.perf_counter() - started) * 1000)
            except subprocess.TimeoutExpired:
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Time Limit Exceeded",
                        expected=expected,
                        actual=None,
                        runtime_ms=int(
                            min(MAX_TIMEOUT_SECONDS, max(0.1, float(time_limit_seconds))) * 1000
                        ),
                        message=(
                            f"Test exceeded the "
                            f"{min(MAX_TIMEOUT_SECONDS, max(0.1, float(time_limit_seconds))):.2f}s "
                            "execution limit."
                        ),
                    )
                )
                continue

            stderr = _truncate((completed.stderr or "").strip())
            stdout_raw = completed.stdout or ""
            stdout = _truncate(stdout_raw)

            if len(stdout_raw) > MAX_OUTPUT_LENGTH:
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Output Limit Exceeded",
                        expected=expected,
                        actual=stdout,
                        runtime_ms=runtime_ms,
                        message=f"Program output exceeded {MAX_OUTPUT_LENGTH} characters.",
                    )
                )
                continue

            if completed.returncode != 0:
                message = stderr or stdout or "Program exited with a non-zero status."
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Runtime Error",
                        expected=expected,
                        actual=stdout,
                        runtime_ms=runtime_ms,
                        message=message,
                    )
                )
                continue

            validator_name = case.get("validator_name")

            if validator_name:
                if not package_root:
                    outcomes.append(
                        TestOutcome(
                            index=index,
                            passed=False,
                            status="Judge Error",
                            expected=expected,
                            actual=stdout,
                            runtime_ms=runtime_ms,
                            message="The imported package has no persisted validator files.",
                        )
                    )
                    continue

                try:
                    validation = run_custom_validator(
                        package_root=package_root,
                        validator_name=str(validator_name),
                        input_data=input_data,
                        answer_data=expected,
                        team_output=stdout,
                        validator_args=case.get("validator_flags") or [],
                        timeout_seconds=validation_time_seconds,
                        output_limit_bytes=validation_output_bytes,
                    )
                except CustomValidatorError as exc:
                    outcomes.append(
                        TestOutcome(
                            index=index,
                            passed=False,
                            status="Judge Error",
                            expected=expected,
                            actual=stdout,
                            runtime_ms=runtime_ms,
                            message=str(exc),
                        )
                    )
                    continue

                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=validation.passed,
                        status=validation.status,
                        expected=expected,
                        actual=stdout,
                        runtime_ms=runtime_ms,
                        message=validation.message,
                    )
                )
            else:
                try:
                    validation = validate_default_output(
                        stdout,
                        expected,
                        case.get("validator_flags"),
                    )
                except UnsupportedValidatorError as exc:
                    raise CodeRejectedError(str(exc)) from exc

                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=validation.passed,
                        status="Passed" if validation.passed else "Wrong Answer",
                        expected=expected,
                        actual=stdout,
                        runtime_ms=runtime_ms,
                        message=None if validation.passed else validation.message,
                    )
                )

    return outcomes


def run_python_tests(
    source: str,
    test_cases: list[dict[str, Any]],
    time_limit_seconds: float = TIMEOUT_SECONDS,
    *,
    memory_limit_mb: int | None = None,
) -> list[TestOutcome]:
    validate_code(source)
    time_limit_seconds = min(
        MAX_TIMEOUT_SECONDS,
        max(0.1, float(time_limit_seconds)),
    )

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
                completed = _run_python_process(
                    script_path,
                    workdir,
                    input_data=None,
                    timeout_seconds=time_limit_seconds,
                    memory_limit_mb=memory_limit_mb,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                outcomes.append(
                    TestOutcome(
                        index=index,
                        passed=False,
                        status="Time Limit Exceeded",
                        expected=expected,
                        actual=None,
                        runtime_ms=int(time_limit_seconds * 1000),
                        message=f"Test exceeded the {time_limit_seconds:.1f}s execution limit.",
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
