from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


class CustomValidatorError(RuntimeError):
    pass


@dataclass(frozen=True)
class ValidatorResult:
    passed: bool
    message: str | None
    status: str


def _resolve_root(package_root: str) -> Path:
    root = Path(package_root)
    if not root.is_absolute():
        root = Path(__file__).resolve().parent.parent / root
    root = root.resolve()
    if not root.is_dir():
        raise CustomValidatorError(f"Problem package storage does not exist: {root}")
    return root


def _find_program(root: Path, program_name: str | None) -> Path:
    candidates: list[Path] = []

    if program_name:
        path = Path(program_name)
        candidates.extend([root / path, root / "output_validators" / path])

    candidates.extend(
        [
            root / "output_validator",
            root / "output_validator.py",
            root / "output_validators" / "default",
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate
        if candidate.is_dir():
            run_file = candidate / "run"
            if run_file.is_file():
                return run_file

            py_files = sorted(candidate.glob("*.py"))
            if len(py_files) == 1:
                return py_files[0]

            cpp_files = sorted(candidate.glob("*.cpp")) + sorted(candidate.glob("*.cc")) + sorted(candidate.glob("*.cxx"))
            if len(cpp_files) == 1:
                return cpp_files[0]

    plural = root / "output_validators"
    if program_name and plural.is_dir():
        direct = plural / program_name
        if direct.is_file():
            return direct
        if direct.is_dir():
            run_file = direct / "run"
            if run_file.is_file():
                return run_file
            py_files = sorted(direct.glob("*.py"))
            if len(py_files) == 1:
                return py_files[0]
            cpp_files = sorted(direct.glob("*.cpp")) + sorted(direct.glob("*.cc")) + sorted(direct.glob("*.cxx"))
            if len(cpp_files) == 1:
                return cpp_files[0]

    raise CustomValidatorError(
        f"Could not locate custom output validator '{program_name or 'output_validator'}'."
    )


def _prepare_command(program: Path, compile_dir: Path) -> tuple[list[str], Path]:
    if program.is_dir():
        run_file = program / "run"
        if not run_file.is_file():
            raise CustomValidatorError(f"Validator directory has no run program: {program}")
        program = run_file

    suffix = program.suffix.lower()

    if suffix in {".py", ".py3"}:
        return [sys.executable, str(program)], program.parent

    if suffix in {".bat", ".cmd"}:
        return ["cmd", "/c", str(program)], program.parent

    if suffix == ".sh":
        if os.name == "nt":
            raise CustomValidatorError("POSIX shell validators are not supported by the local Windows runner.")
        return ["/bin/sh", str(program)], program.parent

    if suffix in {".cpp", ".cc", ".cxx"}:
        compiler = shutil.which("g++")
        if not compiler:
            raise CustomValidatorError(
                "Custom C++ validator requires g++ to be installed and available on PATH."
            )
        compile_dir.mkdir(parents=True, exist_ok=True)
        binary = compile_dir / ("validator.exe" if os.name == "nt" else "validator")
        completed = subprocess.run(
            [
                compiler,
                str(program),
                "-std=c++17",
                "-O2",
                "-o",
                str(binary),
            ],
            cwd=program.parent,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Validator compilation failed.").strip()
            raise CustomValidatorError(_truncate(message))
        return [str(binary)], program.parent

    if suffix in {".exe", ""}:
        return [str(program)], program.parent

    raise CustomValidatorError(
        f"Unsupported custom validator program type: {program.name}"
    )


def _truncate(value: str, limit: int = 8000) -> str:
    return value if len(value) <= limit else value[:limit] + "\n[output truncated]"


def run_custom_validator(
    package_root: str,
    validator_name: str | None,
    input_data: str,
    answer_data: str,
    team_output: str,
    validator_args: list[str] | None = None,
    timeout_seconds: float = 60.0,
    output_limit_bytes: int = 8 * 1024 * 1024,
) -> ValidatorResult:
    root = _resolve_root(package_root)
    args = list(validator_args or [])

    with tempfile.TemporaryDirectory(prefix="codementor-validator-") as temp_dir:
        work = Path(temp_dir)
        input_path = work / "testdata.in"
        answer_path = work / "testdata.ans"
        feedback_dir = work / "feedback"
        feedback_dir.mkdir()

        input_path.write_text(input_data, encoding="utf-8")
        answer_path.write_text(answer_data, encoding="utf-8")

        program = _find_program(root, validator_name)
        try:
            command, cwd = _prepare_command(program, work / "build")
        except subprocess.TimeoutExpired as exc:
            raise CustomValidatorError("Custom validator compilation timed out.") from exc

        argv = command + [
            str(input_path),
            str(answer_path),
            str(feedback_dir) + os.sep,
            *args,
        ]

        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                input=team_output,
                capture_output=True,
                text=True,
                timeout=max(0.1, float(timeout_seconds)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ValidatorResult(
                passed=False,
                status="Judge Error",
                message="Custom output validator exceeded its validation time limit.",
            )
        except OSError as exc:
            raise CustomValidatorError(f"Could not start custom validator: {exc}") from exc

        feedback_bytes = 0
        feedback_messages: list[str] = []
        for feedback_name in ("teammessage.txt", "judgemessage.txt"):
            feedback_path = feedback_dir / feedback_name
            if feedback_path.is_file():
                data = feedback_path.read_bytes()
                feedback_bytes += len(data)
                if feedback_bytes > output_limit_bytes:
                    return ValidatorResult(
                        False,
                        "Custom output validator exceeded its feedback output limit.",
                        "Judge Error",
                    )
                text_value = data.decode("utf-8", errors="replace").strip()
                if text_value:
                    feedback_messages.append(text_value)

        process_output_bytes = len((completed.stdout or "").encode("utf-8")) + len(
            (completed.stderr or "").encode("utf-8")
        )
        if process_output_bytes + feedback_bytes > output_limit_bytes:
            return ValidatorResult(
                False,
                "Custom output validator exceeded its output limit.",
                "Judge Error",
            )

        fallback_message = _truncate(
            (feedback_messages[0] if feedback_messages else "")
            or (completed.stderr or "").strip()
            or (completed.stdout or "").strip()
        )

        if completed.returncode == 42:
            return ValidatorResult(True, fallback_message or None, "Passed")

        if completed.returncode == 43:
            return ValidatorResult(
                False,
                fallback_message or "The custom output validator rejected the output.",
                "Wrong Answer",
            )

        return ValidatorResult(
            False,
            fallback_message or (
                f"Custom output validator failed with exit code {completed.returncode}."
            ),
            "Judge Error",
        )
