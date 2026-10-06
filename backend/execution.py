from __future__ import annotations

import ast
import math
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.validator import UnsupportedValidatorError, validate_default_output

MAX_CODE_LENGTH = 40_000
TIMEOUT_SECONDS = 2.0
MAX_TIMEOUT_SECONDS = 10.0
MAX_COMPILE_SECONDS = 10.0
MIN_MEMORY_MB = 64
DEFAULT_MEMORY_MB = 256
MAX_MEMORY_MB = 1024
MAX_OUTPUT_LENGTH = 12_000
MAX_OUTPUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 32 * 1024
MAX_TEST_CASES = 200
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_EXECUTION_SECONDS = 120.0
DOCKER_STARTUP_GRACE_SECONDS = 8.0
DOCKER_STOP_GRACE_SECONDS = 3.0
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PIDS = 64
MAX_NOFILE = 256

SUPPORTED_LANGUAGES = {"Python", "C++", "Java", "JavaScript", "TypeScript", "Go", "Rust"}
LANGUAGE_EXTENSIONS = {
    "Python": ".py", "C++": ".cpp", "Java": ".java", "JavaScript": ".js",
    "TypeScript": ".ts", "Go": ".go", "Rust": ".rs",
}
COMPILED_LANGUAGES = {"C++", "Java", "TypeScript", "Go", "Rust"}

EXECUTION_SANDBOX = os.getenv("EXECUTION_SANDBOX", "docker").strip().lower()
EXECUTION_DOCKER_IMAGE = os.getenv("EXECUTION_DOCKER_IMAGE", "codementor-multi-runtime:latest").strip()
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
PRODUCTION_ENVS = {"prod", "production"}


class CodeRejectedError(ValueError):
    """Submission/configuration is not valid for the execution service."""


class SandboxUnavailableError(RuntimeError):
    """The required Docker sandbox is unavailable."""


@dataclass
class TestOutcome:
    index: int
    passed: bool
    status: str
    expected: Any | None
    actual: Any | None
    runtime_ms: int
    message: str | None = None


@dataclass(frozen=True)
class _ContainerResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool
    oom_killed: bool
    output_limit_exceeded: bool = False
    runtime_ms: int = 0


def _truncate(value: str, limit: int = MAX_OUTPUT_LENGTH) -> str:
    return value if len(value) <= limit else value[:limit] + "\n[output truncated]"


def _normalize_time_limit(value: float | int | None) -> float:
    if value is None:
        value = TIMEOUT_SECONDS
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise CodeRejectedError("Invalid execution time limit.") from exc
    if not math.isfinite(value) or value <= 0:
        raise CodeRejectedError("Execution time limit must be a positive finite number.")
    return min(MAX_TIMEOUT_SECONDS, max(0.1, value))


def _normalize_memory_limit(value: int | None) -> int:
    if value is None:
        return DEFAULT_MEMORY_MB
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise CodeRejectedError("Invalid execution memory limit.") from exc
    if value <= 0:
        raise CodeRejectedError("Execution memory limit must be positive.")
    return min(MAX_MEMORY_MB, max(MIN_MEMORY_MB, value))


def syntax_diagnostic(source: str) -> dict[str, object]:
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
        end_column = max(column + 1, int(end_offset) if end_offset is not None else column + 1)
        return {
            "valid": False, "message": exc.msg or "Syntax error.", "line": line,
            "column": column, "end_line": end_line, "end_column": end_column,
        }
    return {
        "valid": True, "message": None, "line": None, "column": None,
        "end_line": None, "end_column": None,
    }


def _sandbox_mode() -> str:
    if EXECUTION_SANDBOX != "docker":
        raise SandboxUnavailableError(
            "Code execution requires EXECUTION_SANDBOX=docker. Host-native execution is disabled."
        )
    return "docker"


def _ensure_docker_available() -> None:
    _sandbox_mode()
    if not shutil.which("docker"):
        raise SandboxUnavailableError(
            "Docker CLI was not found. Install/start Docker Desktop on Windows or Docker Engine on Linux."
        )
    try:
        info = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=5, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxUnavailableError("Docker daemon did not respond.") from exc
    except OSError as exc:
        raise SandboxUnavailableError(f"Could not start Docker: {exc}") from exc
    if info.returncode != 0:
        detail = _truncate((info.stderr or info.stdout or "").strip())
        raise SandboxUnavailableError(
            f"Docker daemon is unavailable: {detail or 'unknown Docker error'}"
        )
    image = subprocess.run(
        ["docker", "image", "inspect", EXECUTION_DOCKER_IMAGE],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if image.returncode != 0:
        raise SandboxUnavailableError(
            f"Docker image '{EXECUTION_DOCKER_IMAGE}' was not found. Build it with: "
            "docker build -t codementor-multi-runtime:latest "
            "-f docker/multi-runtime/Dockerfile docker/multi-runtime"
        )


def _docker_base_command(workdir: str, *, memory_limit_mb: int, docker_name: str) -> list[str]:
    return [
        "docker", "run", "--name", docker_name, "--init", "--network", "none", "--pid", "private",
        "--cpus", "1.0", "--cpu-period", "100000", "--cpu-quota", "100000",
        "--memory", f"{memory_limit_mb}m", "--memory-swap", f"{memory_limit_mb}m",
        "--pids-limit", str(MAX_PIDS), "--ipc", "private", "--shm-size", "16m", "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--tmpfs", "/runner:rw,nosuid,nodev,exec,size=256m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--security-opt", "seccomp=default",
        "--ulimit", f"nproc={MAX_PIDS}:{MAX_PIDS}", "--ulimit", f"nofile={MAX_NOFILE}:{MAX_NOFILE}",
        "--ulimit", f"fsize={MAX_FILE_BYTES}:{MAX_FILE_BYTES}", "--ulimit", "core=0:0",
        "--mount", f"type=bind,source={os.path.abspath(workdir)},target=/workspace,readonly",
        "--workdir", "/workspace", "--user", "65532:65532",
        "--env", "PATH=/opt/codementor/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "--env", "HOME=/tmp", "--env", "TMPDIR=/tmp", "--env", "LANG=C.UTF-8", "--env", "LC_ALL=C.UTF-8",
        "--env", "TZ=UTC", "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONUNBUFFERED=1",
        "--env", "PYTHONHASHSEED=0", "--env", "GOCACHE=/tmp/go-cache", "--env", "GOMODCACHE=/tmp/go-mod-cache",
        "--env", "GOMAXPROCS=1", "--env", "RUST_BACKTRACE=0",
    ]


def _language_commands(
    language: str, source_path: str, workdir: str
) -> tuple[list[str] | None, list[str], None]:
    del workdir
    source_name = os.path.basename(source_path)
    source = shlex.quote(f"/workspace/{source_name}")
    if language == "Python":
        return None, ["python3", "-I", "-B", f"/workspace/{source_name}"], None
    if language == "C++":
        return [
            "sh", "-c",
            f"mkdir -p /runner/artifacts && g++ -std=c++20 -O2 -pipe -s {source} -o /runner/artifacts/program",
        ], ["/workspace/build/program"], None
    if language == "Java":
        return [
            "sh", "-c",
            f"mkdir -p /runner/artifacts/classes && javac -encoding UTF-8 -d /runner/artifacts/classes {source}",
        ], ["java", "-Djava.io.tmpdir=/tmp", "-cp", "/workspace/build/classes", "Main"], None
    if language == "JavaScript":
        return None, ["node", "--use-strict", f"/workspace/{source_name}"], None
    if language == "TypeScript":
        return [
            "tsc", "--target", "ES2022", "--module", "commonjs", "--strict", "false", "--skipLibCheck",
            "--types", "node", "--typeRoots", "/opt/codementor/node_modules/@types",
            "--outDir", "/runner/artifacts/tsc", f"/workspace/{source_name}",
        ], ["node", "/workspace/build/tsc/solution.js"], None
    if language == "Go":
        return [
            "sh", "-c",
            f"mkdir -p /runner/artifacts && go build -o /runner/artifacts/program {source}",
        ], ["/workspace/build/program"], None
    if language == "Rust":
        return [
            "sh", "-c",
            f"mkdir -p /runner/artifacts && rustc -O {source} -o /runner/artifacts/program",
        ], ["/workspace/build/program"], None
    raise CodeRejectedError(f"Unsupported language runtime: {language}.")


def validate_code(source: str, *, stdio: bool = True) -> None:
    del stdio
    if len(source) > MAX_CODE_LENGTH:
        raise CodeRejectedError(f"Code exceeds the {MAX_CODE_LENGTH} character limit.")
    try:
        ast.parse(source)
    except SyntaxError as exc:
        raise CodeRejectedError(f"Syntax Error: {exc.msg} (line {exc.lineno}).") from exc


def extract_error_location(message: str | None) -> tuple[int, int | None] | None:
    if not message:
        return None
    patterns = [
        (r"(?:Main\.java|solution\.[A-Za-z0-9_]+)\((\d+),(\d+)\)", True),
        (r"(?:Main\.java|solution\.[A-Za-z0-9_]+):(\d+):(\d+)", True),
        (r"(?:Main\.java|solution\.[A-Za-z0-9_]+):(\d+)\b", False),
        (r"<user_code>[^,]*,\s*line\s+(\d+)", False),
        (r"line\s+(\d+)\b", False),
    ]
    for pattern, has_column in patterns:
        match = re.search(pattern, message)
        if match:
            return int(match.group(1)), int(match.group(2)) if has_column else None
    return None


def extract_error_line(message: str | None) -> int | None:
    location = extract_error_location(message)
    return location[0] if location else None


def _output_reader(stream, buffer: bytearray, limit: int, exceeded: threading.Event) -> None:
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            room = limit + 1 - len(buffer)
            if room > 0:
                buffer.extend(chunk[:room])
            if len(buffer) > limit:
                exceeded.set()
                return
    except OSError:
        return


def _kill_container(name: str) -> None:
    try:
        subprocess.run(
            ["docker", "kill", "--signal", "KILL", name],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _remove_container(name: str) -> None:
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _inspect_container_oom(name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.OOMKilled}}", name],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _wrap_with_timeout(command: list[str], timeout_seconds: float) -> list[str]:
    timeout_token = f"__CODEMENTOR_TIMEOUT_{uuid.uuid4().hex}__"
    oom_token = f"__CODEMENTOR_OOM_{uuid.uuid4().hex}__"
    quoted = shlex.join(command)
    shell = (
        "set +e; "
        "cm_oom_count() { value=$(grep -E '^oom_kill[[:space:]]+' /sys/fs/cgroup/memory.events 2>/dev/null | awk '{print $2}'); if [ -z \"$value\" ]; then value=0; fi; printf '%s' \"$value\"; }; "
        "oom_before=$(cm_oom_count); "
        f"timeout --signal=TERM --kill-after=0.2s {timeout_seconds:.3f}s {quoted}; rc=$?; "
        "oom_after=$(cm_oom_count); "
        f"[ \"$rc\" -eq 124 ] && printf '%s\\n' {shlex.quote(timeout_token)} >&2; "
        f"[ \"$oom_after\" -gt \"$oom_before\" ] 2>/dev/null && printf '%s\\n' {shlex.quote(oom_token)} >&2; "
        "exit $rc"
    )
    return ["/bin/sh", "-c", shell]


def _run_docker_command(
    workdir: str, command: list[str], *, input_data: str | None, memory_limit_mb: int,
    timeout_seconds: float, output_limit_bytes: int, stderr_limit_bytes: int,
    outer_timeout_seconds: float | None = None,
) -> _ContainerResult:
    name = f"codementor-run-{uuid.uuid4().hex[:20]}"
    docker_command = _docker_base_command(
        workdir, memory_limit_mb=memory_limit_mb, docker_name=name
    ) + [EXECUTION_DOCKER_IMAGE, *_wrap_with_timeout(command, timeout_seconds)]
    started = time.perf_counter()
    process = subprocess.Popen(
        docker_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    exceeded = threading.Event()
    threads = [
        threading.Thread(
            target=_output_reader,
            args=(process.stdout, stdout_buffer, output_limit_bytes, exceeded),
            daemon=True,
        ),
        threading.Thread(
            target=_output_reader,
            args=(process.stderr, stderr_buffer, stderr_limit_bytes, exceeded),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    payload = (input_data or "").encode("utf-8")

    def feed() -> None:
        try:
            if process.stdin:
                process.stdin.write(payload)
                process.stdin.close()
        except (BrokenPipeError, OSError):
            try:
                if process.stdin:
                    process.stdin.close()
            except OSError:
                pass

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    timed_out = False
    try:
        deadline = time.monotonic() + (
            outer_timeout_seconds
            or (timeout_seconds + DOCKER_STARTUP_GRACE_SECONDS)
        )
        while process.poll() is None:
            if exceeded.is_set():
                _kill_container(name)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _kill_container(name)
                break
            time.sleep(0.02)
        try:
            process.wait(timeout=DOCKER_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_container(name)
            process.kill()
            process.wait(timeout=1)
        feeder.join(timeout=1)
        for thread in threads:
            thread.join(timeout=1)
        stdout = bytes(stdout_buffer[:output_limit_bytes]).decode("utf-8", errors="replace")
        stderr = bytes(stderr_buffer[:stderr_limit_bytes]).decode("utf-8", errors="replace")
        oom = _inspect_container_oom(name)
        timeout_marker = re.search(r"__CODEMENTOR_TIMEOUT_[0-9a-f]+__", stderr) is not None
        oom_marker = re.search(r"__CODEMENTOR_OOM_[0-9a-f]+__", stderr) is not None
        return _ContainerResult(
            stdout=stdout,
            stderr=stderr,
            returncode=int(process.returncode if process.returncode is not None else -1),
            timed_out=timed_out or timeout_marker,
            oom_killed=oom or oom_marker,
            output_limit_exceeded=exceeded.is_set(),
            runtime_ms=int((time.perf_counter() - started) * 1000),
        )
    finally:
        _remove_container(name)


def _compile_submission(
    source: str, language: str, workdir: Path
) -> tuple[bool, str | None, int]:
    if language not in COMPILED_LANGUAGES:
        return True, None, 0
    source_name = (
        "Main.java"
        if language == "Java"
        else f"solution{LANGUAGE_EXTENSIONS[language]}"
    )
    compile_argv, _, _ = _language_commands(language, source_name, str(workdir))
    assert compile_argv is not None
    build_dir = workdir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    result_name = f"codementor-compile-{uuid.uuid4().hex[:20]}"
    cmd = _docker_base_command(
        str(workdir), memory_limit_mb=MAX_MEMORY_MB, docker_name=result_name
    ) + [EXECUTION_DOCKER_IMAGE, *_wrap_with_timeout(compile_argv, MAX_COMPILE_SECONDS)]
    started = time.perf_counter()
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = process.communicate(
            timeout=MAX_COMPILE_SECONDS + DOCKER_STARTUP_GRACE_SECONDS
        )
    except subprocess.TimeoutExpired:
        _kill_container(result_name)
        return False, "Compilation exceeded the 10.00s compilation limit.", int(
            (time.perf_counter() - started) * 1000
        )
    runtime_ms = int((time.perf_counter() - started) * 1000)
    try:
        stdout = stdout or b""
        stderr = stderr or b""
        if process.returncode is None or process.returncode != 0:
            text = (stderr or stdout).decode("utf-8", errors="replace")
            if b"__CODEMENTOR_TIMEOUT_" in stderr:
                return False, "Compilation exceeded the 10.00s compilation limit.", runtime_ms
            if _inspect_container_oom(result_name):
                return False, "Compiler exceeded the execution service memory limit.", runtime_ms
            return False, _truncate(text.strip() or "Compilation failed."), runtime_ms
        cp = subprocess.run(
            ["docker", "cp", f"{result_name}:/runner/artifacts/.", str(build_dir)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if cp.returncode != 0:
            return False, "Compiler artifacts could not be retrieved from Docker.", runtime_ms
        required = (
            build_dir / "classes" / "Main.class"
            if language == "Java"
            else build_dir / "tsc" / "solution.js"
            if language == "TypeScript"
            else build_dir / "program"
        )
        if not required.exists():
            return False, "Compiler produced no executable artifact.", runtime_ms
        return True, None, runtime_ms
    finally:
        _remove_container(result_name)


def _status_from_runtime(
    result: _ContainerResult,
) -> tuple[str, str | None]:
    if result.oom_killed:
        return "Memory Limit Exceeded", "The process exceeded the container memory limit."
    if result.timed_out:
        return "Time Limit Exceeded", "The process exceeded its time limit."
    if result.output_limit_exceeded:
        return "Runtime Error", f"Program output exceeded the {MAX_OUTPUT_BYTES} byte output limit."
    if result.returncode != 0:
        return (
            "Runtime Error",
            result.stderr.strip()
            or result.stdout.strip()
            or f"Process exited with status {result.returncode}.",
        )
    return "Passed", None


def overall_status(outcomes: list[TestOutcome]) -> str:
    if not outcomes:
        return "System Error"
    statuses = {outcome.status for outcome in outcomes}
    for status in (
        "Compilation Error", "Memory Limit Exceeded", "Time Limit Exceeded",
        "Runtime Error", "System Error"
    ):
        if status in statuses:
            return status
    return "Accepted" if all(outcome.passed for outcome in outcomes) else "Wrong Answer"


def _execute_submission(
    source: str,
    language: str,
    test_cases: list[dict[str, Any]],
    time_limit_seconds: float,
    *,
    memory_limit_mb: int | None,
) -> list[TestOutcome]:
    if language not in SUPPORTED_LANGUAGES:
        raise CodeRejectedError(f"Unsupported language runtime: {language}.")
    if len(source) > MAX_CODE_LENGTH:
        raise CodeRejectedError(
            f"Code exceeds the {MAX_CODE_LENGTH} character limit."
        )
    if not test_cases:
        raise CodeRejectedError("The problem contains no executable test cases.")
    if len(test_cases) > MAX_TEST_CASES:
        raise CodeRejectedError(
            f"Too many test cases. Maximum supported is {MAX_TEST_CASES}."
        )
    limit = _normalize_time_limit(time_limit_seconds)
    memory = _normalize_memory_limit(memory_limit_mb)
    for index, case in enumerate(test_cases, start=1):
        if len(str(case.get("input", "")).encode("utf-8")) > MAX_INPUT_BYTES:
            raise CodeRejectedError(
                f"Test input {index} exceeds the {MAX_INPUT_BYTES} byte limit."
            )
    _ensure_docker_available()

    if language == "Python":
        diagnostic = syntax_diagnostic(source)
        if not diagnostic["valid"]:
            message = str(
                diagnostic["message"] or "Python compilation failed."
            )
            return [
                TestOutcome(
                    i, False, "Compilation Error",
                    str(c.get("expected_output", "")), None, 0,
                    f"{message} (line {diagnostic['line']}).",
                )
                for i, c in enumerate(test_cases, 1)
            ]

    source_name = (
        "Main.java"
        if language == "Java"
        else f"solution{LANGUAGE_EXTENSIONS[language]}"
    )
    _, run_argv, _ = _language_commands(language, source_name, "")
    with tempfile.TemporaryDirectory(prefix="codementor-exec-") as temp:
        workdir = Path(temp)
        source_path = workdir / source_name
        source_path.write_text(source, encoding="utf-8", newline="\n")
        if os.name != "nt":
            os.chmod(workdir, 0o755)
            os.chmod(source_path, 0o644)

        compiled, message, compile_ms = _compile_submission(
            source, language, workdir
        )
        if not compiled:
            status = (
                "Time Limit Exceeded"
                if message and message.startswith("Compilation exceeded")
                else "Compilation Error"
            )
            return [
                TestOutcome(
                    i, False, status,
                    str(c.get("expected_output", "")), None, compile_ms, message
                )
                for i, c in enumerate(test_cases, 1)
            ]

        outcomes: list[TestOutcome] = []
        started_all = time.monotonic()
        for index, case in enumerate(test_cases, start=1):
            remaining = MAX_TOTAL_EXECUTION_SECONDS - (
                time.monotonic() - started_all
            )
            expected = str(case.get("expected_output", ""))
            if remaining <= 0:
                outcomes.append(
                    TestOutcome(
                        index, False, "Time Limit Exceeded", expected, None, 0,
                        "The submission exceeded the global execution safety limit.",
                    )
                )
                continue
            result = _run_docker_command(
                str(workdir),
                run_argv,
                input_data=str(case.get("input", "")),
                memory_limit_mb=memory,
                timeout_seconds=min(limit, remaining),
                output_limit_bytes=MAX_OUTPUT_BYTES,
                stderr_limit_bytes=MAX_STDERR_BYTES,
                outer_timeout_seconds=min(limit, remaining)
                + DOCKER_STARTUP_GRACE_SECONDS,
            )
            status, detail = _status_from_runtime(result)
            actual = result.stdout
            if status == "Passed":
                try:
                    validation = validate_default_output(
                        actual, expected, case.get("validator_flags")
                    )
                except UnsupportedValidatorError as exc:
                    outcomes.append(
                        TestOutcome(
                            index, False, "System Error", expected, actual,
                            result.runtime_ms, str(exc),
                        )
                    )
                    continue
                outcomes.append(
                    TestOutcome(
                        index, validation.passed,
                        "Passed" if validation.passed else "Wrong Answer",
                        expected, actual, result.runtime_ms,
                        None if validation.passed else validation.message,
                    )
                )
            else:
                outcomes.append(
                    TestOutcome(
                        index, False, status, expected,
                        _truncate(actual), result.runtime_ms,
                        _truncate(detail or status),
                    )
                )
        return outcomes


def run_language_stdio_tests(
    source: str,
    language: str,
    test_cases: list[dict[str, Any]],
    time_limit_seconds: float = TIMEOUT_SECONDS,
    *,
    memory_limit_mb: int | None = None,
) -> list[TestOutcome]:
    return _execute_submission(
        source, language, test_cases, time_limit_seconds,
        memory_limit_mb=memory_limit_mb,
    )


def run_python_stdio_tests(
    source: str,
    test_cases: list[dict[str, Any]],
    time_limit_seconds: float = TIMEOUT_SECONDS,
    *,
    memory_limit_mb: int | None = None,
    package_root: str | None = None,
    validation_time_seconds: float = 60.0,
    validation_output_bytes: int = 8 * 1024 * 1024,
) -> list[TestOutcome]:
    del package_root, validation_time_seconds, validation_output_bytes
    return run_language_stdio_tests(
        source, "Python", test_cases,
        time_limit_seconds, memory_limit_mb=memory_limit_mb,
    )
