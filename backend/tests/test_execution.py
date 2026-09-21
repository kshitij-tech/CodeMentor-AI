import unittest
from unittest.mock import patch

from backend.execution import (
    CodeRejectedError,
    MAX_MEMORY_MB,
    MAX_TIMEOUT_SECONDS,
    _sandbox_mode,
    syntax_diagnostic,
    _language_commands,
    LANGUAGE_EXTENSIONS,
)


class ExecutionSandboxTests(unittest.TestCase):
    def test_invalid_sandbox_mode_is_rejected(self):
        with patch("backend.execution.EXECUTION_SANDBOX", "unknown"):
            with self.assertRaises(CodeRejectedError):
                _sandbox_mode()

    def test_production_requires_docker(self):
        with patch("backend.execution.APP_ENV", "production"):
            with patch("backend.execution.EXECUTION_SANDBOX", "local"):
                with self.assertRaises(CodeRejectedError):
                    _sandbox_mode()

    def test_development_local_mode_is_allowed(self):
        with patch("backend.execution.APP_ENV", "development"):
            with patch("backend.execution.EXECUTION_SANDBOX", "local"):
                self.assertEqual(_sandbox_mode(), "local")

    def test_resource_safety_caps_are_bounded(self):
        self.assertEqual(MAX_TIMEOUT_SECONDS, 10.0)
        self.assertEqual(MAX_MEMORY_MB, 1024)

    def test_syntax_diagnostic_marks_offending_token(self):
        diagnostic = syntax_diagnostic("def solve():\n    return )\n")
        self.assertFalse(diagnostic["valid"])
        self.assertEqual(diagnostic["line"], 2)
        self.assertGreaterEqual(diagnostic["column"], 1)
        self.assertGreater(diagnostic["end_column"], diagnostic["column"])

    def test_syntax_diagnostic_accepts_valid_python(self):
        diagnostic = syntax_diagnostic("def solve():\n    return 42\n")
        self.assertTrue(diagnostic["valid"])
        self.assertIsNone(diagnostic["line"])
        self.assertIsNone(diagnostic["column"])

    def test_all_supported_languages_have_runtime_definitions(self):
        for language in LANGUAGE_EXTENSIONS:
            compile_command, run_command, docker_shell = _language_commands(
                language,
                "/tmp/solution" + LANGUAGE_EXTENSIONS[language],
                "/tmp/codementor",
            )
            self.assertTrue(run_command)
            if language in {"C++", "Java", "TypeScript", "Go", "Rust"}:
                self.assertTrue(compile_command)
                self.assertTrue(docker_shell)
            else:
                self.assertIsNone(compile_command)
                self.assertIsNone(docker_shell)

    def test_java_runtime_uses_main_class_filename(self):
        compile_command, run_command, docker_shell = _language_commands(
            "Java", "/tmp/Main.java", "/tmp/codementor"
        )
        self.assertIn("javac", compile_command)
        self.assertEqual(run_command[-1], "Main")
        self.assertIn("/runner/classes", docker_shell[0])


if __name__ == "__main__":
    unittest.main()
