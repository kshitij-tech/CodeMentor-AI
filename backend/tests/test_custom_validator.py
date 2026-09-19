import tempfile
import unittest
from pathlib import Path

from backend.custom_validator import run_custom_validator


VALIDATOR = """from pathlib import Path
import sys

input_path, answer_path, feedback_dir, *args = sys.argv[1:]
values = Path(input_path).read_text().split()
output = sys.stdin.read().split()

if output == values:
    raise SystemExit(42)

Path(feedback_dir, "teammessage.txt").write_text(
    "Output must reproduce the input tokens.",
    encoding="utf-8",
)
raise SystemExit(43)
"""


class CustomValidatorTests(unittest.TestCase):
    def test_python_validator_accepts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            validator_dir = root / "output_validator"
            validator_dir.mkdir()
            (validator_dir / "validate.py").write_text(VALIDATOR, encoding="utf-8")

            result = run_custom_validator(
                package_root=str(root),
                validator_name="output_validator",
                input_data="1 2 3\n",
                answer_data="ignored\n",
                team_output="1 2 3\n",
                validator_args=[],
                timeout_seconds=2,
            )

            self.assertTrue(result.passed)
            self.assertEqual(result.status, "Passed")

    def test_python_validator_rejects_with_feedback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            validator_dir = root / "output_validator"
            validator_dir.mkdir()
            (validator_dir / "validate.py").write_text(VALIDATOR, encoding="utf-8")

            result = run_custom_validator(
                package_root=str(root),
                validator_name="output_validator",
                input_data="1 2 3\n",
                answer_data="ignored\n",
                team_output="1 9 3\n",
                validator_args=[],
                timeout_seconds=2,
            )

            self.assertFalse(result.passed)
            self.assertEqual(result.status, "Wrong Answer")
            self.assertIn("reproduce", result.message or "")


if __name__ == "__main__":
    unittest.main()
