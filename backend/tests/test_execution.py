from __future__ import annotations

import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.execution import (
    CodeRejectedError,
    SandboxUnavailableError,
    _ContainerResult,
    _docker_base_command,
    _language_commands,
    _normalize_memory_limit,
    _normalize_time_limit,
    _status_from_runtime,
    extract_error_line,
    extract_error_location,
    overall_status,
    syntax_diagnostic,
    validate_code,
    LANGUAGE_EXTENSIONS,
    MAX_MEMORY_MB,
    MAX_OUTPUT_BYTES,
    MAX_TIMEOUT_SECONDS,
)


class ExecutionConfigTests(unittest.TestCase):
    def test_docker_is_the_only_sandbox_mode(self):
        from backend.execution import _sandbox_mode

        with patch("backend.execution.EXECUTION_SANDBOX", "docker"):
            self.assertEqual(_sandbox_mode(), "docker")

    def test_local_mode_is_rejected_as_unsafe(self):
        from backend.execution import _sandbox_mode

        with patch("backend.execution.EXECUTION_SANDBOX", "local"):
            with self.assertRaises(SandboxUnavailableError):
                _sandbox_mode()

    def test_limits_are_clamped(self):
        self.assertEqual(_normalize_time_limit(100), MAX_TIMEOUT_SECONDS)
        self.assertEqual(_normalize_time_limit(0.01), 0.1)
        self.assertEqual(_normalize_memory_limit(10_000), MAX_MEMORY_MB)
        self.assertEqual(_normalize_memory_limit(1), 64)

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(CodeRejectedError):
            _normalize_time_limit(0)
        with self.assertRaises(CodeRejectedError):
            _normalize_memory_limit(0)


class LanguageSupportTests(unittest.TestCase):
    def test_every_supported_language_has_stdio_commands(self):
        for language, extension in LANGUAGE_EXTENSIONS.items():
            with self.subTest(language=language):
                compile_argv, run_argv, compatibility = _language_commands(
                    language,
                    f"/tmp/solution{extension}",
                    "/tmp/work",
                )
                self.assertTrue(run_argv)
                self.assertIsNone(compatibility)
                if language in {"Python", "JavaScript"}:
                    self.assertIsNone(compile_argv)
                else:
                    self.assertTrue(compile_argv)

    def test_java_and_typescript_paths_are_deterministic(self):
        compile_argv, run_argv, _ = _language_commands(
            "Java", "/tmp/Main.java", "/tmp/work"
        )
        self.assertIn("/workspace/Main.java", compile_argv[-1])
        self.assertEqual(run_argv[-1], "Main")

        compile_argv, run_argv, _ = _language_commands(
            "TypeScript", "/tmp/solution.ts", "/tmp/work"
        )
        self.assertIn("/runner/artifacts/tsc", compile_argv)
        self.assertEqual(run_argv, ["node", "/workspace/build/tsc/solution.js"])


class DockerHardeningTests(unittest.TestCase):
    def test_container_command_has_security_boundary_flags(self):
        command = _docker_base_command(
            r"C:codementor	emp",
            memory_limit_mb=256,
            docker_name="codementor-test",
        )
        joined = "\n".join(command)
        for expected in [
            "--init",
            "--network\nnone",
            "--pid\nprivate",
            "--cpus\n1.0",
            "--cpu-period\n100000",
            "--cpu-quota\n100000",
            "--memory\n256m",
            "--memory-swap\n256m",
            "--pids-limit\n64",
            "--read-only",
            "--cap-drop\nALL",
            "--security-opt\nno-new-privileges",
            "--security-opt\nseccomp=default",
            "--ulimit\nnproc=64:64",
            "--ulimit\nnofile=256:256",
            "--ulimit\nfsize=67108864:67108864",
            "--ulimit\ncore=0:0",
            "--user\n65532:65532",
        ]:
            self.assertIn(expected, joined)
        self.assertIn("/tmp:rw,noexec,nosuid,nodev,size=64m", joined)
        self.assertIn("/runner:rw,nosuid,nodev,exec,size=256m", joined)
        self.assertIn("type=bind", joined)
        self.assertIn("target=/workspace", joined)
        self.assertIn("readonly", joined)


class PythonAdmissionTests(unittest.TestCase):
    def test_stdio_python_allows_normal_competitive_programming_imports(self):
        validate_code("import sys\nimport os\nprint(int(sys.stdin.read()))\n", stdio=True)

    def test_python_syntax_diagnostic_reports_location(self):
        result = syntax_diagnostic("def solve(:\n")
        self.assertFalse(result["valid"])
        self.assertEqual(result["line"], 1)
        self.assertIsNotNone(result["column"])

    def test_syntax_diagnostic_accepts_valid_code(self):
        result = syntax_diagnostic("import sys\nprint(sys.stdin.read())\n")
        self.assertTrue(result["valid"])

    def test_static_validation_does_not_blacklist_filesystem_or_input_calls(self):
        validate_code("import os\nprint(input())\n", stdio=True)


class ClassificationTests(unittest.TestCase):
    def test_overall_status_precedence_and_final_states(self):
        def outcome(status: str, passed: bool = False):
            return SimpleNamespace(status=status, passed=passed)

        expected = [
            ("Compilation Error", "Compilation Error"),
            ("Memory Limit Exceeded", "Memory Limit Exceeded"),
            ("Time Limit Exceeded", "Time Limit Exceeded"),
            ("Runtime Error", "Runtime Error"),
            ("System Error", "System Error"),
        ]
        for status, result in expected:
            with self.subTest(status=status):
                self.assertEqual(
                    overall_status([outcome(status), outcome("Wrong Answer")]),
                    result,
                )
        self.assertEqual(overall_status([outcome("Passed", True)]), "Accepted")
        self.assertEqual(overall_status([outcome("Wrong Answer")]), "Wrong Answer")
        self.assertEqual(overall_status([]), "System Error")

    def test_function_style_execution_is_not_exposed(self):
        import backend.execution as execution

        self.assertFalse(hasattr(execution, "run_language_function_tests"))
        self.assertFalse(hasattr(execution, "run_python_tests"))

    def test_every_runtime_status_is_classified(self):
        cases = [
            ("Passed", _ContainerResult("42\n", "", 0, False, False)),
            ("Runtime Error", _ContainerResult("", "boom", 1, False, False)),
            ("Time Limit Exceeded", _ContainerResult("", "", 0, True, False)),
            ("Memory Limit Exceeded", _ContainerResult("", "", 137, False, True)),
            ("Runtime Error", _ContainerResult("", "", 0, False, False, True)),
        ]
        for expected, result in cases:
            with self.subTest(expected=expected):
                self.assertEqual(_status_from_runtime(result)[0], expected)

    def test_error_location_parsing(self):
        self.assertEqual(
            extract_error_location("solution.cpp:12:7: error: expected ';'"),
            (12, 7),
        )
        self.assertEqual(
            extract_error_location("Main.java:4:13: error: ';' expected"),
            (4, 13),
        )
        self.assertEqual(
            extract_error_location("solution.ts(8,15): error TS1005"),
            (8, 15),
        )
        self.assertEqual(
            extract_error_location("thread 'main' panicked at solution.rs:9:13"),
            (9, 13),
        )
        self.assertEqual(extract_error_line('File "<user_code>", line 9'), 9)


class RuntimeImageTests(unittest.TestCase):
    def test_multi_runtime_image_declares_all_requested_runtimes(self):
        dockerfile = pathlib.Path(__file__).parents[2] / "docker" / "multi-runtime" / "Dockerfile"
        text = dockerfile.read_text(encoding="utf-8")
        for package in [
            "g++",
            "golang-go",
            "openjdk-17-jdk-headless",
            "nodejs",
            "python3",
            "rustc",
            "cargo",
        ]:
            self.assertIn(package, text)
        self.assertIn(
            "npm install --prefix /opt/codementor typescript @types/node",
            text,
        )
        self.assertIn("USER 65532:65532", text)


if __name__ == "__main__":
    unittest.main()
