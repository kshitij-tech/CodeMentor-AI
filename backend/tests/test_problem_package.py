import unittest

from backend.execution import run_python_stdio_tests
from backend.problem_package import package_to_problem


class ProblemPackageTests(unittest.TestCase):
    def test_package_is_normalized(self):
        files = {
            "problem.yaml": b"""problem_format_version: 2025-09
name: Hello Package
uuid: test-uuid
source: CodeMentor Fixture
keywords: [strings, implementation]
limits:
  time_limit: 1.5
  memory: 512
validation: default
""",
            "problem.md": b"# Hello Package\n\nRead an integer and print it twice.",
            "data/sample/1.in": b"4\n",
            "data/sample/1.ans": b"8\n",
            "data/secret/1.in": b"7\n",
            "data/secret/1.ans": b"14\n",
        }

        problem = package_to_problem(files, "fixture")
        self.assertEqual(problem["title"], "Hello Package")
        self.assertEqual(problem["execution_mode"], "stdio")
        self.assertEqual(problem["time_limit_ms"], 1500)
        self.assertEqual(problem["memory_limit_mb"], 512)
        self.assertEqual(len(problem["test_cases"]), 2)
        self.assertTrue(problem["package_metadata"]["judge_supported"])

    def test_stdio_execution(self):
        source = """import sys

n = int(sys.stdin.readline())
print(n * 2)
"""
        cases = [
            {"input": "4\n", "expected_output": "8\n", "visibility": "sample"},
            {"input": "7\n", "expected_output": "14\n", "visibility": "secret"},
        ]

        results = run_python_stdio_tests(source, cases, time_limit_seconds=1)
        self.assertEqual([result.status for result in results], ["Passed", "Passed"])


    def test_extracts_dot_ans_files(self):
        files = {
            "problem.yaml": b"name: Answer Mapping Test\n",
            "problem.md": b"# Answer Mapping Test\n",
            "data/sample/0.in": b"hello\n",
            "data/sample/0.ans": b"world\n",
        }
        problem = package_to_problem(files, "fixture")
        self.assertEqual(problem["test_cases"][0]["expected_output"], "world\n")


if __name__ == "__main__":
    unittest.main()
