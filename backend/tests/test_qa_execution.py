
import unittest
from unittest.mock import patch

from backend.execution import CodeRejectedError, TestOutcome
from backend.tests.qa_support import (
    TestDatabase,
    SyncASGIClient,
    add_problem,
    add_user,
    auth_headers,
    auth_token,
    build_test_app,
    reset_catalog_cache,
)


class ExecutionApiQualityTests(unittest.TestCase):
    def setUp(self):
        reset_catalog_cache()
        self.database = TestDatabase()
        self.db = self.database.session()
        self.app = build_test_app(self.database)
        self.client = SyncASGIClient(self.app)
        self.user = add_user(self.db, "execution-qa@example.com")
        self.headers = auth_headers(auth_token(self.user))

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.database.close()
        reset_catalog_cache()

    def test_syntax_validation_endpoint_reports_python_error_location(self):
        response = self.client.request(
            "POST",
            "/execution/validate",
            headers=self.headers,
            json_body={
                "problem_slug": "not-needed-for-validation",
                "language": "Python",
                "code": "def solve():\n    return )\n",
                "mode": "run",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["valid"])
        self.assertEqual(response.json["line"], 2)
        self.assertGreaterEqual(response.json["column"], 1)

    def test_missing_auth_is_rejected_before_execution(self):
        response = self.client.request(
            "POST",
            "/execution/run",
            json_body={
                "problem_slug": "missing",
                "language": "Python",
                "code": "print(1)",
                "mode": "run",
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_code_rejection_is_mapped_to_rejected_api_result(self):
        problem = add_problem(self.db, slug="rejection")
        with patch(
            "backend.routers.execution.run_python_stdio_tests",
            side_effect=CodeRejectedError(
                "solution.py:7:3: prohibited import"
            ),
        ):
            response = self.client.request(
                "POST",
                "/execution/run",
                headers=self.headers,
                json_body={
                    "problem_slug": problem.slug,
                    "language": "Python",
                    "code": "print(1)",
                    "mode": "run",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "Rejected")
        self.assertIn("prohibited import", response.json["summary"])
        self.assertIsNone(response.json["error_line"])
        self.assertIsNone(response.json["error_column"])

    def test_secret_expected_output_is_redacted_from_api_response(self):
        problem = add_problem(
            self.db,
            slug="secret-redaction",
            test_cases=[
                {
                    "input": "1\n",
                    "expected_output": "2\n",
                    "visibility": "sample",
                },
                {
                    "input": "9\n",
                    "expected_output": "10\n",
                    "visibility": "secret",
                },
            ],
        )

        outcomes = [
            TestOutcome(
                index=1,
                passed=False,
                status="Wrong Answer",
                expected="2\n",
                actual="1\n",
                runtime_ms=3,
                message="Wrong answer",
            ),
            TestOutcome(
                index=2,
                passed=False,
                status="Wrong Answer",
                expected="10\n",
                actual="9\n",
                runtime_ms=4,
                message="Wrong answer",
            ),
        ]

        with patch(
            "backend.routers.execution.run_python_stdio_tests",
            return_value=outcomes,
        ):
            response = self.client.request(
                "POST",
                "/execution/run",
                headers=self.headers,
                json_body={
                    "problem_slug": problem.slug,
                    "language": "Python",
                    "code": "print(1)",
                    "mode": "submit",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["results"][0]["expected"], "2\n")
        self.assertIsNone(response.json["results"][1]["expected"])
        self.assertEqual(response.json["results"][1]["actual"], "9\n")

    def test_unsupported_custom_validator_is_reported_without_running_code(self):
        add_problem(
            self.db,
            slug="custom-validator-unsupported",
            package_metadata={"judge_supported": True},
            test_cases=[
                {
                    "input": "1\n",
                    "expected_output": "1\n",
                    "visibility": "sample",
                    "validator_name": "output_validator",
                },
            ],
        )
        with patch("backend.routers.execution.run_python_stdio_tests") as runner:
            response = self.client.request(
                "POST",
                "/execution/run",
                headers=self.headers,
                json_body={
                    "problem_slug": "custom-validator-unsupported",
                    "language": "C++",
                    "code": "int main() { return 0; }",
                    "mode": "run",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "Unsupported Problem Format")
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
