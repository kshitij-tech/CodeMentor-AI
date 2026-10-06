
import unittest
from unittest.mock import patch

from backend.ai import AIProviderError
from backend.models import MentorMessage

from backend.tests.qa_support import (
    TestDatabase,
    SyncASGIClient,
    add_attempt,
    add_mentor_session,
    add_problem,
    add_user,
    add_profile,
    auth_headers,
    auth_token,
    build_test_app,
    reset_catalog_cache,
)


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        reset_catalog_cache()
        self.database = TestDatabase()
        self.db = self.database.session()
        self.app = build_test_app(self.database)
        self.client = SyncASGIClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.database.close()
        reset_catalog_cache()

    def test_authentication_and_profile_lifecycle(self):
        protected = self.client.request("GET", "/profile")
        self.assertEqual(protected.status_code, 401)

        short_password = self.client.request(
            "POST",
            "/auth/register",
            json_body={"email": "new@example.com", "password": "short"},
        )
        self.assertEqual(short_password.status_code, 400)

        registered = self.client.request(
            "POST",
            "/auth/register",
            json_body={"email": "New@Example.COM", "password": "password123"},
        )
        self.assertEqual(registered.status_code, 201)
        self.assertEqual(registered.json["email"], "new@example.com")

        duplicate = self.client.request(
            "POST",
            "/auth/register",
            json_body={"email": " NEW@example.com ", "password": "password123"},
        )
        self.assertEqual(duplicate.status_code, 409)

        login = self.client.request(
            "POST",
            "/auth/login",
            json_body={"email": "NEW@example.com", "password": "password123"},
        )
        self.assertEqual(login.status_code, 200)
        token = login.json["access_token"]
        headers = auth_headers(token)

        me = self.client.request("GET", "/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json["email"], "new@example.com")

        profile = self.client.request(
            "PUT",
            "/profile",
            headers=headers,
            json_body={
                "full_name": "Test User",
                "bio": "A QA profile",
                "leetcode_username": "qa_user",
                "preferred_language": "Python",
                "experience_level": "Intermediate",
                "target_role": "Backend Engineer",
                "target_companies": ["Acme", "Globex"],
                "preparation_timeline": "12 weeks",
            },
        )
        self.assertEqual(profile.status_code, 200)
        self.assertTrue(profile.json["onboarding_completed"])
        self.assertEqual(profile.json["target_companies"], ["Acme", "Globex"])

        fetched = self.client.request("GET", "/profile", headers=headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json["target_role"], "Backend Engineer")

    def test_invalid_token_and_unknown_user_are_rejected(self):
        bad = self.client.request(
            "GET",
            "/auth/me",
            headers={"authorization": "Bearer not-a-token"},
        )
        self.assertEqual(bad.status_code, 401)
        self.assertIn("Invalid or expired", bad.json["detail"])

        user = add_user(self.db, "gone@example.com")
        token = auth_token(user)
        self.db.delete(user)
        self.db.commit()

        deleted_user = self.client.request(
            "GET",
            "/auth/me",
            headers=auth_headers(token),
        )
        self.assertEqual(deleted_user.status_code, 401)
        self.assertIn("no longer exists", deleted_user.json["detail"])

    def test_problem_catalog_api_filters_invalid_catalog_entries(self):
        valid_easy = add_problem(
            self.db,
            slug="two-sum",
            title="Two Sum",
            difficulty="Easy",
            topics=["array", "hash_map"],
        )
        add_problem(
            self.db,
            slug="binary-search",
            title="Binary Search",
            difficulty="Medium",
            topics=["binary_search"],
        )
        add_problem(
            self.db,
            slug="unknown-difficulty",
            title="Unknown Difficulty",
            difficulty="Unknown",
        )
        add_problem(
            self.db,
            slug="foreign-text",
            title="中文题目",
            description="这是一个测试题目",
        )
        reset_catalog_cache()

        headers = auth_headers(auth_token(add_user(self.db, "catalog@example.com")))

        listing = self.client.request(
            "GET",
            "/problems?difficulty=easy&topic=Hashing%20%26%20Hash%20Maps",
            headers=headers,
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json["total"], 1)
        self.assertEqual(listing.json["items"][0]["id"], valid_easy.id)

        by_search = self.client.request(
            "GET",
            "/problems?search=binary&limit=1",
            headers=headers,
        )
        self.assertEqual(by_search.status_code, 200)
        self.assertEqual(by_search.json["has_more"], False)
        self.assertEqual(by_search.json["items"][0]["title"], "Binary Search")

        topics = self.client.request("GET", "/problems/topics", headers=headers)
        self.assertEqual(topics.status_code, 200)
        self.assertTrue(
            any(
                item["name"] == "Arrays & Strings"
                for item in topics.json["topics"]
            )
        )
        self.assertNotIn(
            "Unknown",
            [item["name"] for item in topics.json["difficulties"]],
        )

        taxonomy = self.client.request("GET", "/problems/taxonomy", headers=headers)
        self.assertEqual(taxonomy.status_code, 200)
        self.assertEqual(
            taxonomy.json["difficulties"],
            ["Easy", "Medium", "Hard"],
        )

        detail = self.client.request("GET", "/problems/two-sum", headers=headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json["execution_mode"], "stdio")
        self.assertNotIn("Examples:", detail.json["description"])

        missing = self.client.request(
            "GET",
            "/problems/no-such-problem",
            headers=headers,
        )
        self.assertEqual(missing.status_code, 404)

    def test_workspace_isolation_and_history_are_user_scoped(self):
        problem = add_problem(self.db, slug="workspace-problem")
        user_a = add_user(self.db, "alice@example.com")
        user_b = add_user(self.db, "bob@example.com")
        token_a = auth_token(user_a)
        token_b = auth_token(user_b)

        save_a = self.client.request(
            "PUT",
            "/workspace",
            headers=auth_headers(token_a),
            json_body={
                "problem_slug": problem.slug,
                "language": "Python",
                "code": "print('alice')",
            },
        )
        save_b = self.client.request(
            "PUT",
            "/workspace",
            headers=auth_headers(token_b),
            json_body={
                "problem_slug": problem.slug,
                "language": "Python",
                "code": "print('bob')",
            },
        )
        self.assertEqual(save_a.status_code, 200)
        self.assertEqual(save_b.status_code, 200)

        read_a = self.client.request(
            "GET",
            f"/workspace?problem_slug={problem.slug}&language=Python",
            headers=auth_headers(token_a),
        )
        read_b = self.client.request(
            "GET",
            f"/workspace?problem_slug={problem.slug}&language=Python",
            headers=auth_headers(token_b),
        )
        self.assertEqual(read_a.json["code"], "print('alice')")
        self.assertEqual(read_b.json["code"], "print('bob')")

        save_a_cpp = self.client.request(
            "PUT",
            "/workspace",
            headers=auth_headers(token_a),
            json_body={
                "problem_slug": problem.slug,
                "language": "C++",
                "code": "int main() {}",
            },
        )
        self.assertEqual(save_a_cpp.status_code, 200)

        attempt = add_attempt(
            self.db,
            user_id=user_a.id,
            problem_id=problem.id,
            status="Wrong Answer",
            code="print('alice attempt')",
        )
        history_a = self.client.request(
            "GET",
            f"/workspace/history?problem_slug={problem.slug}",
            headers=auth_headers(token_a),
        )
        history_b = self.client.request(
            "GET",
            f"/workspace/history?problem_slug={problem.slug}",
            headers=auth_headers(token_b),
        )
        self.assertEqual(history_a.status_code, 200)
        self.assertEqual(history_b.status_code, 200)
        self.assertEqual(history_a.json["items"][0]["id"], attempt.id)
        self.assertEqual(history_a.json["items"][0]["code"], "print('alice attempt')")
        self.assertEqual(history_b.json["items"], [])

    def test_recommendation_is_locked_until_active_problem_is_solved(self):
        current = add_problem(
            self.db,
            slug="current-problem",
            title="Current Problem",
            difficulty="Easy",
            topics=["Arrays & Strings"],
        )
        other = add_problem(
            self.db,
            slug="next-problem",
            title="Next Problem",
            difficulty="Easy",
            topics=["Hashing & Hash Maps"],
        )
        user = add_user(self.db, "recommend@example.com")
        add_profile(self.db, user.id, experience_level="Beginner")

        headers = auth_headers(auth_token(user))
        locked = self.client.request(
            "GET",
            f"/recommendations/next?current_problem_id={current.id}",
            headers=headers,
        )
        self.assertEqual(locked.status_code, 200)
        self.assertTrue(locked.json["locked_until_solved"])
        self.assertEqual(locked.json["problem"]["id"], current.id)

        add_attempt(
            self.db,
            user_id=user.id,
            problem_id=current.id,
            status="Accepted",
        )
        reset_catalog_cache()
        unlocked = self.client.request(
            "GET",
            f"/recommendations/next?current_problem_id={current.id}",
            headers=headers,
        )
        self.assertEqual(unlocked.status_code, 200)
        self.assertFalse(unlocked.json["locked_until_solved"])
        self.assertEqual(unlocked.json["problem"]["id"], other.id)

    def test_analytics_counts_only_current_user_and_handles_invalid_timezone(self):
        problem_a = add_problem(
            self.db,
            slug="analytics-a",
            title="Analytics A",
            topics=["Arrays & Strings"],
        )
        problem_b = add_problem(
            self.db,
            slug="analytics-b",
            title="Analytics B",
            topics=["Binary Search"],
        )
        user_a = add_user(self.db, "analytics-a@example.com")
        user_b = add_user(self.db, "analytics-b@example.com")
        from datetime import datetime, timezone

        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        day_one = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
        day_two = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)

        add_attempt(
            self.db,
            user_id=user_a.id,
            problem_id=problem_a.id,
            created_at=day_one,
        )
        add_attempt(
            self.db,
            user_id=user_a.id,
            problem_id=problem_b.id,
            created_at=day_two,
        )
        add_attempt(
            self.db,
            user_id=user_b.id,
            problem_id=problem_a.id,
            created_at=day_one,
        )
        session = add_mentor_session(
            self.db,
            user_id=user_a.id,
            scope="dashboard",
        )
        from backend.tests.qa_support import add_mentor_message

        add_mentor_message(
            self.db,
            session_id=session.id,
            role="assistant",
            content="hint",
            action="hint",
        )

        with patch("backend.routers.analytics._utc_now", return_value=now):
            summary = self.client.request(
                "GET",
                "/analytics/summary?timezone_name=Asia%2FKolkata",
                headers=auth_headers(auth_token(user_a)),
            )
            self.assertEqual(summary.status_code, 200)
            data = summary.json
            self.assertEqual(data["total_attempts"], 2)
            self.assertEqual(data["total_solved"], 2)
            self.assertEqual(data["current_streak"], 2)
            self.assertEqual(data["ai_hints"], 1)
            self.assertEqual(data["average_runtime_ms"], 25.0)

            invalid_tz = self.client.request(
                "GET",
                "/analytics/summary?timezone_name=Not%2FAReal",
                headers=auth_headers(auth_token(user_a)),
            )
            self.assertEqual(invalid_tz.status_code, 200)

    def test_mentor_provider_failure_returns_503_and_preserves_user_message(self):
        problem = add_problem(self.db, slug="mentor-problem")
        user = add_user(self.db, "mentor@example.com")
        headers = auth_headers(auth_token(user))

        with patch(
            "backend.routers.mentor.mentor_response",
            side_effect=AIProviderError(
                "AI model unavailable.",
                retryable=True,
            ),
        ):
            response = self.client.request(
                "POST",
                "/mentor/analyze",
                headers=headers,
                json_body={
                    "problem_slug": problem.slug,
                    "language": "Python",
                    "code": "print(1)",
                    "action": "hint",
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("AI model unavailable", response.json["detail"])

        persisted = self.db.query(MentorMessage).all()
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].role, "user")

    def test_mentor_rejects_cross_user_session(self):
        problem = add_problem(self.db, slug="mentor-isolation")
        owner = add_user(self.db, "mentor-owner@example.com")
        intruder = add_user(self.db, "mentor-intruder@example.com")
        session = add_mentor_session(
            self.db,
            user_id=owner.id,
            problem_id=problem.id,
            scope="practice",
        )
        response = self.client.request(
            "POST",
            "/mentor/analyze",
            headers=auth_headers(auth_token(intruder)),
            json_body={
                "problem_slug": problem.slug,
                "language": "Python",
                "code": "print(1)",
                "action": "question",
                "question": "Can I access another user's session?",
                "session_id": session.id,
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_execution_error_paths_and_secret_output_protection(self):
        problem = add_problem(
            self.db,
            slug="execution-problem",
            test_cases=[
                {
                    "input": "1\n",
                    "expected_output": "2\n",
                    "visibility": "sample",
                },
                {
                    "input": "999\n",
                    "expected_output": "1000\n",
                    "visibility": "secret",
                },
            ],
        )
        user = add_user(self.db, "execution@example.com")
        headers = auth_headers(auth_token(user))

        with patch(
            "backend.routers.execution.run_python_stdio_tests",
            side_effect=FileNotFoundError,
        ):
            unavailable = self.client.request(
                "POST",
                "/execution/run",
                headers=headers,
                json_body={
                    "problem_slug": problem.slug,
                    "language": "Python",
                    "code": "print(2)",
                    "mode": "submit",
                },
            )
        self.assertEqual(unavailable.status_code, 200)
        self.assertEqual(unavailable.json["status"], "Runtime Unavailable")

        self.assertEqual(
            self.client.request(
                "POST",
                "/execution/run",
                headers=headers,
                json_body={
                    "problem_slug": "missing",
                    "language": "Python",
                    "code": "print(2)",
                },
            ).status_code,
            404,
        )

        with patch(
            "backend.routers.execution.run_python_stdio_tests",
        ) as runner:
            from backend.execution import TestOutcome

            runner.return_value = [
                TestOutcome(
                    index=1,
                    passed=False,
                    status="Wrong Answer",
                    expected="2\n",
                    actual="1\n",
                    runtime_ms=4,
                    message="Wrong answer",
                ),
                TestOutcome(
                    index=2,
                    passed=False,
                    status="Wrong Answer",
                    expected="1000\n",
                    actual="999\n",
                    runtime_ms=5,
                    message="Wrong answer",
                ),
            ]
            submitted = self.client.request(
                "POST",
                "/execution/run",
                headers=headers,
                json_body={
                    "problem_slug": problem.slug,
                    "language": "Python",
                    "code": "print(1)",
                    "mode": "submit",
                },
            )
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.json["results"][0]["expected"], "2\n")
        self.assertIsNone(submitted.json["results"][1]["expected"])


if __name__ == "__main__":
    unittest.main()
