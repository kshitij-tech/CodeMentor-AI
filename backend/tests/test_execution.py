import unittest
from unittest.mock import patch

from backend.execution import CodeRejectedError, _sandbox_mode


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


if __name__ == "__main__":
    unittest.main()
