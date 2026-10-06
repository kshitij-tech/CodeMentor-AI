import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    CodingAttempt,
    CodeWorkspace,
    MentorMessage,
    MentorSession,
    Problem,
    User,
    UserProfile,
)
from backend.routers import analytics, auth, mentor, profile, recommendations, workspace
from backend.security import (
    ALGORITHM,
    JWT_ISSUER,
    SECRET_KEY,
    create_access_token,
    reset_security_state_for_tests,
    validate_security_configuration,
)


class AuthenticationSecurityTests(unittest.TestCase):
    def setUp(self):
        reset_security_state_for_tests()

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.Session = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
        )
        Base.metadata.create_all(bind=self.engine)

        self.app = FastAPI()
        for router in (
            auth.router,
            profile.router,
            workspace.router,
            mentor.router,
            analytics.router,
            recommendations.router,
        ):
            self.app.include_router(router)

        def override_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)

        recommendations._catalog_cache.update(
            {
                "loaded_at": 0.0,
                "rows": [],
                "topics": [],
                "difficulties": [],
                "total": 0,
            }
        )

    def tearDown(self):
        self.client.close()
        reset_security_state_for_tests()
        self.engine.dispose()

    def _register(self, email, password="StrongPassword!2026"):
        response = self.client.post(
            "/auth/register",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 201, response.text)

    def _login(self, email, password="StrongPassword!2026"):
        response = self.client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _headers(self, tokens):
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    def test_registration_hashes_password_and_login_issues_access_and_refresh(self):
        self._register("Alice@Example.com")

        with self.Session() as db:
            user = db.query(User).filter(User.email == "alice@example.com").one()
            self.assertNotEqual(user.password_hash, "StrongPassword!2026")
            self.assertTrue(user.password_hash.startswith("$argon2"))

        tokens = self._login("alice@example.com")
        self.assertEqual(tokens["token_type"], "bearer")
        self.assertTrue(tokens["access_token"])
        self.assertTrue(tokens["refresh_token"])
        self.assertGreater(tokens["expires_in"], 0)
        self.assertGreater(tokens["refresh_expires_in"], tokens["expires_in"])

        me = self.client.get("/auth/me", headers=self._headers(tokens))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "alice@example.com")

    def test_duplicate_and_invalid_registration_are_rejected(self):
        self._register("alice@example.com")

        duplicate = self.client.post(
            "/auth/register",
            json={
                "email": " ALICE@example.com ",
                "password": "AnotherStrong!2026",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

        short = self.client.post(
            "/auth/register",
            json={"email": "short@example.com", "password": "short123"},
        )
        self.assertEqual(short.status_code, 400)

        long_password = self.client.post(
            "/auth/register",
            json={"email": "long@example.com", "password": "A" * 129},
        )
        self.assertEqual(long_password.status_code, 400)

        invalid_email = self.client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "StrongPassword!2026"},
        )
        self.assertEqual(invalid_email.status_code, 422)

    def test_missing_invalid_and_expired_tokens_are_rejected(self):
        self._register("alice@example.com")
        tokens = self._login("alice@example.com")

        missing = self.client.get("/auth/me")
        self.assertEqual(missing.status_code, 401)

        malformed = self.client.get(
            "/auth/me",
            headers={"Authorization": "Bearer definitely-not-a-jwt"},
        )
        self.assertEqual(malformed.status_code, 401)
        self.assertEqual(malformed.headers["www-authenticate"], "Bearer")

        expired = jwt.encode(
            {
                "sub": "1",
                "type": "access",
                "jti": "expired-test",
                "iat": datetime.now(timezone.utc) - timedelta(hours=1),
                "nbf": datetime.now(timezone.utc) - timedelta(hours=1),
                "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
                "iss": JWT_ISSUER,
            },
            SECRET_KEY,
            algorithm=ALGORITHM,
        )
        response = self.client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {expired}"},
        )
        self.assertEqual(response.status_code, 401)

        wrong_type = self.client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
        )
        self.assertEqual(wrong_type.status_code, 401)

    def test_refresh_requires_a_token(self):
        response = self.client.post("/auth/refresh")
        self.assertEqual(response.status_code, 401)

    def test_refresh_rotates_token_and_rejects_reuse(self):
        self._register("alice@example.com")
        tokens = self._login("alice@example.com")

        refreshed = self.client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        self.assertEqual(refreshed.status_code, 200)
        refreshed_tokens = refreshed.json()
        self.assertNotEqual(refreshed_tokens["access_token"], tokens["access_token"])
        self.assertNotEqual(refreshed_tokens["refresh_token"], tokens["refresh_token"])

        reused = self.client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        self.assertEqual(reused.status_code, 401)

    def test_logout_revokes_access_and_refresh_tokens(self):
        self._register("alice@example.com")
        tokens = self._login("alice@example.com")

        logout = self.client.post(
            "/auth/logout",
            headers=self._headers(tokens),
            json={"refresh_token": tokens["refresh_token"]},
        )
        self.assertEqual(logout.status_code, 200)

        me = self.client.get("/auth/me", headers=self._headers(tokens))
        self.assertEqual(me.status_code, 401)

        refresh = self.client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        self.assertEqual(refresh.status_code, 401)

    def test_login_and_registration_are_rate_limited(self):
        self._register("alice@example.com")

        for _ in range(5):
            response = self.client.post(
                "/auth/login",
                json={
                    "email": "alice@example.com",
                    "password": "WrongPassword!2026",
                },
            )
            self.assertEqual(response.status_code, 401)

        limited = self.client.post(
            "/auth/login",
            json={
                "email": "alice@example.com",
                "password": "WrongPassword!2026",
            },
        )
        self.assertEqual(limited.status_code, 429)
        self.assertGreaterEqual(int(limited.headers["retry-after"]), 1)

    def test_cross_user_resources_are_isolated(self):
        self._register("alice@example.com")
        self._register("bob@example.com")
        alice = self._login("alice@example.com")
        bob = self._login("bob@example.com")

        with self.Session() as db:
            alice_user = db.query(User).filter(User.email == "alice@example.com").one()
            bob_user = db.query(User).filter(User.email == "bob@example.com").one()

            problem_one = Problem(
                slug="problem-one",
                title="Two Sum",
                difficulty="Easy",
                topics=["Arrays & Strings"],
                description="Find a pair.",
                constraints=[],
                examples=[],
                test_cases=[],
                starter_code={},
            )
            problem_two = Problem(
                slug="problem-two",
                title="Binary Search",
                difficulty="Easy",
                topics=["Binary Search"],
                description="Search an array.",
                constraints=[],
                examples=[],
                test_cases=[],
                starter_code={},
            )
            db.add_all([problem_one, problem_two])
            db.flush()

            db.add(
                CodeWorkspace(
                    user_id=bob_user.id,
                    problem_id=problem_one.id,
                    language="Python",
                    code="print('bob-private-code')",
                )
            )
            db.add(
                CodingAttempt(
                    user_id=bob_user.id,
                    problem_id=problem_one.id,
                    language="Python",
                    mode="submit",
                    code="print('bob-submission')",
                    status="Accepted",
                    summary="1/1 tests passed.",
                    results=[],
                )
            )
            db.add(
                CodingAttempt(
                    user_id=alice_user.id,
                    problem_id=problem_two.id,
                    language="Python",
                    mode="submit",
                    code="print('alice-submission')",
                    status="Accepted",
                    summary="1/1 tests passed.",
                    results=[],
                )
            )
            db.add(
                UserProfile(
                    user_id=bob_user.id,
                    full_name="Bob",
                    preferred_language="Python",
                    experience_level="Beginner",
                    target_role="Backend Engineer",
                )
            )

            bob_session = MentorSession(
                user_id=bob_user.id,
                scope="practice",
                problem_id=problem_one.id,
                title="Bob's private session",
            )
            db.add(bob_session)
            db.flush()
            db.add(
                MentorMessage(
                    session_id=bob_session.id,
                    role="user",
                    content="Bob secret message",
                    action="question",
                    hint_level=1,
                )
            )
            db.commit()
            bob_session_id = bob_session.id

        alice_headers = self._headers(alice)
        bob_headers = self._headers(bob)

        workspace_response = self.client.get(
            "/workspace",
            params={"problem_slug": "problem-one", "language": "Python"},
            headers=alice_headers,
        )
        self.assertEqual(workspace_response.status_code, 200)
        self.assertIsNone(workspace_response.json()["code"])

        history_response = self.client.get(
            "/workspace/history",
            params={"problem_slug": "problem-one"},
            headers=alice_headers,
        )
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(history_response.json()["items"], [])

        mentor_response = self.client.get(
            f"/mentor/sessions/{bob_session_id}",
            headers=alice_headers,
        )
        self.assertEqual(mentor_response.status_code, 404)

        profile_response = self.client.get("/profile", headers=alice_headers)
        self.assertEqual(profile_response.status_code, 200)
        self.assertIsNone(profile_response.json()["full_name"])

        analytics_response = self.client.get(
            "/analytics/summary",
            headers=alice_headers,
        )
        self.assertEqual(analytics_response.status_code, 200)
        self.assertEqual(analytics_response.json()["total_attempts"], 1)

        recommendations._catalog_cache.update(
            {
                "loaded_at": 0.0,
                "rows": [],
                "topics": [],
                "difficulties": [],
                "total": 0,
            }
        )
        recommendation_response = self.client.get(
            "/recommendations/next",
            headers=alice_headers,
        )
        self.assertEqual(recommendation_response.status_code, 200)
        self.assertNotEqual(recommendation_response.json()["problem"]["id"], 2)

        bob_workspace = self.client.get(
            "/workspace",
            params={"problem_slug": "problem-one", "language": "Python"},
            headers=bob_headers,
        )
        self.assertEqual(bob_workspace.status_code, 200)
        self.assertEqual(
            bob_workspace.json()["code"],
            "print('bob-private-code')",
        )

        bob_mentor = self.client.get(
            f"/mentor/sessions/{bob_session_id}",
            headers=bob_headers,
        )
        self.assertEqual(bob_mentor.status_code, 200)
        self.assertEqual(
            bob_mentor.json()["messages"][0]["content"],
            "Bob secret message",
        )

    def test_secure_configuration_rejects_insecure_production_secret(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "JWT_SECRET_KEY": "dev-only-secret-change-me",
                "CORS_ORIGINS": "https://example.com",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "JWT_SECRET_KEY"):
                validate_security_configuration()

    def test_secure_configuration_requires_explicit_production_cors(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "JWT_SECRET_KEY": "x" * 32,
                "CORS_ORIGINS": "",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "CORS_ORIGINS"):
                validate_security_configuration()

    def test_cors_configuration_rejects_wildcards_and_null(self):
        from backend import security

        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "JWT_SECRET_KEY": "x" * 32,
                "CORS_ORIGINS": "*,null",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "wildcard"):
                security.get_cors_origins()


if __name__ == "__main__":
    unittest.main()
