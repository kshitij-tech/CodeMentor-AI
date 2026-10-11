
import unittest
from unittest.mock import patch

from backend.ai import (
    AIProviderError,
    _parse_mentor_response,
    _strip_visible_thinking,
)
from backend.models import MentorMessage
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


class AIResponseReliabilityTests(unittest.TestCase):
    def test_invalid_json_is_rejected(self):
        with self.assertRaises(AIProviderError):
            _parse_mentor_response("{not valid json")

    def test_non_object_json_is_rejected(self):
        for raw in ("[]", '"answer"', "null", "42"):
            with self.subTest(raw=raw):
                with self.assertRaises(AIProviderError):
                    _parse_mentor_response(raw)

    def test_missing_answer_without_patch_is_rejected(self):
        with self.assertRaisesRegex(
            AIProviderError,
            "missing a valid 'answer'",
        ):
            _parse_mentor_response('{"error_line": 4, "patch": null}')

    def test_malformed_patch_is_discarded_without_losing_answer(self):
        result = _parse_mentor_response(
            '{"answer":"Use the other boundary.","patch":{"start_line":"nope","end_line":2}}'
        )
        self.assertEqual(result["answer"], "Use the other boundary.")
        self.assertIsNone(result["patch"])

    def test_unclosed_thinking_block_never_reaches_the_user(self):
        result = _strip_visible_thinking(
            "<think>private reasoning that must stay hidden"
        )
        self.assertEqual(result, "")

    def test_dashboard_model_unavailable_returns_503_and_persists_user_message(self):
        reset_catalog_cache()
        database = TestDatabase()
        app = build_test_app(database)
        client = SyncASGIClient(app)
        db = database.session()
        try:
            user = add_user(db, "dashboard-model@example.com")
            with patch(
                "backend.routers.mentor.mentor_response",
                side_effect=AIProviderError(
                    "The configured model is unavailable.",
                    retryable=True,
                ),
            ):
                response = client.request(
                    "POST",
                    "/mentor/chat",
                    headers=auth_headers(auth_token(user)),
                    json_body={"question": "Help me plan my study session."},
                )

            self.assertEqual(response.status_code, 503)
            self.assertIn("model is unavailable", response.json["detail"])

            messages = db.query(MentorMessage).all()
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].role, "user")
        finally:
            app.dependency_overrides.clear()
            db.close()
            database.close()
            reset_catalog_cache()

    def test_malformed_mentor_api_result_returns_503_instead_of_storing_empty_answer(self):
        reset_catalog_cache()
        database = TestDatabase()
        app = build_test_app(database)
        client = SyncASGIClient(app)
        db = database.session()
        try:
            problem = add_problem(db, slug="malformed-mentor")
            user = add_user(db, "malformed-mentor@example.com")

            with patch(
                "backend.routers.mentor.mentor_response",
                return_value=[],
            ):
                response = client.request(
                    "POST",
                    "/mentor/analyze",
                    headers=auth_headers(auth_token(user)),
                    json_body={
                        "problem_slug": problem.slug,
                        "language": "Python",
                        "code": "print(1)",
                        "action": "hint",
                    },
                )

            self.assertEqual(response.status_code, 503)
            self.assertIn("invalid response", response.json["detail"].lower())

            messages = db.query(MentorMessage).all()
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].role, "user")
        finally:
            app.dependency_overrides.clear()
            db.close()
            database.close()
            reset_catalog_cache()


if __name__ == "__main__":
    unittest.main()
