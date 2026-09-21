import unittest
from unittest.mock import patch

from backend.execution import (
    CodeRejectedError,
    MAX_MEMORY_MB,
    MAX_TIMEOUT_SECONDS,
    _sandbox_mode,
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


if __name__ == "__main__":
    unittest.main()
