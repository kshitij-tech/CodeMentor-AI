import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from fastapi import HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
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
from backend.schemas import UserCreate
from backend.security import (
    ALGORITHM,
    JWT_ISSUER,
    SECRET_KEY,
    reset_security_state_for_tests,
    validate_security_configuration,
)


class DummyRequest:
    client = SimpleNamespace(host="127.0.0.1")


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

    def tearDown(self):
        reset_security_state_for_tests()
        self.engine.dispose()

    def _register(self, email, password="StrongPassword!2026"):
        with self.Session() as db:
            return auth.register(
                UserCreate(email=email, password=password),
                DummyRequest(),
                Response(),
                db,
            )

    def _login(self, email, password="StrongPassword!2026"):
        with self.Session() as db:
            return auth.login(
                auth.LoginRequest(email=email, password=password),
                DummyRequest(),
                Response(),
                db,
            )

    def _user(self, email):
        with self.Session() as db:
            user = db.query(User).filter(User.email == email).one()
            db.expunge(user)
            return user

    def _access_credentials(self, tokens):
        return HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=tokens.access_token,
        )

    def test_registration_hashes_password_and_login_issues_access_and_refresh(self):
        self._register("Alice@Example.com")

        with self.Session() as db:
            user = db.query(User).filter(User.email == "alice@example.com").one()
            self.assertNotEqual(user.password_hash, "StrongPassword!2026")
            self.assertTrue(user.password_hash.startswith("$argon2"))

        tokens = self._login("alice@example.com")
        self.assertEqual(tokens.token_type, "bearer")
        self.assertTrue(tokens.access_token)
        self.assertTrue(tokens.refresh_token)
        self.assertGreater(tokens.expires_in, 0)
        self.assertGreater(tokens.refresh_expires_in, tokens.expires_in)

        with self.Session() as db:
            me = auth.get_current_user(self._access_credentials(tokens), db)
            self.assertEqual(me.email, "alice@example.com")

    def test_duplicate_and_invalid_registration_are_rejected(self):
        self._register("alice@example.com")

        with self.Session() as db:
            with self.assertRaises(HTTPException) as duplicate:
                auth.register(
                    UserCreate(
                        email=" ALICE@example.com ",
                        password="AnotherStrong!2026",
                    ),
                    DummyRequest(),
                    Response(),
                    db,
                )
            self.assertEqual(duplicate.exception.status_code, 409)

            with self.assertRaises(HTTPException) as short:
                auth.register(
                    UserCreate(email="short@example.com", password="short123"),
                    DummyRequest(),
                    Response(),
                    db,
                )
            self.assertEqual(short.exception.status_code, 400)

            with self.assertRaises(HTTPException) as long_password:
                auth.register(
                    UserCreate(email="long@example.com", password="A" * 129),
                    DummyRequest(),
                    Response(),
                    db,
                )
            self.assertEqual(long_password.exception.status_code, 400)

            with self.assertRaises(HTTPException) as invalid_email:
                auth.register(
                    UserCreate(
                        email="not-an-email",
                        password="StrongPassword!2026",
                    ),
                    DummyRequest(),
                    Response(),
                    db,
                )
            self.assertEqual(invalid_email.exception.status_code, 422)

    def test_malformed_stored_password_hash_returns_401(self):
        with self.Session() as db:
            db.add(
                User(
                    email="broken@example.com",
                    password_hash="not-a-supported-password-hash",
                )
            )
            db.commit()

            with self.assertRaises(HTTPException) as context:
                auth.login(
                    auth.LoginRequest(
                        email="broken@example.com",
                        password="StrongPassword!2026",
                    ),
                    DummyRequest(),
                    Response(),
                    db,
                )
            self.assertEqual(context.exception.status_code, 401)

    def test_missing_invalid_expired_and_wrong_type_tokens_are_rejected(self):
        self._register("alice@example.com")
        tokens = self._login("alice@example.com")

        with self.Session() as db:
            with self.assertRaises(HTTPException) as missing:
                auth.get_current_user(None, db)
            self.assertEqual(missing.exception.status_code, 401)

            malformed_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials="definitely-not-a-jwt",
            )
            with self.assertRaises(HTTPException) as malformed:
                auth.get_current_user(malformed_credentials, db)
            self.assertEqual(malformed.exception.status_code, 401)
            self.assertEqual(malformed.exception.headers["WWW-Authenticate"], "Bearer")

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
            with self.assertRaises(HTTPException) as expired_context:
                auth.get_current_user(
                    HTTPAuthorizationCredentials(
                        scheme="Bearer",
                        credentials=expired,
                    ),
                    db,
                )
            self.assertEqual(expired_context.exception.status_code, 401)

            with self.assertRaises(HTTPException) as wrong_type:
                auth.get_current_user(
                    HTTPAuthorizationCredentials(
                        scheme="Bearer",
                        credentials=tokens.refresh_token,
                    ),
                    db,
                )
            self.assertEqual(wrong_type.exception.status_code, 401)

    def test_refresh_requires_token_and_rotates_token(self):
        self._register("alice@example.com")
        tokens = self._login("alice@example.com")

        with self.assertRaises(HTTPException) as missing:
            auth.refresh(auth.RefreshRequest(), DummyRequest(), Response(), None)
        self.assertEqual(missing.exception.status_code, 401)

        with self.Session() as db:
            refreshed = auth.refresh(
                auth.RefreshRequest(refresh_token=tokens.refresh_token),
                DummyRequest(),
                Response(),
                db,
            )
        self.assertNotEqual(refreshed.access_token, tokens.access_token)
        self.assertNotEqual(refreshed.refresh_token, tokens.refresh_token)

        with self.Session() as db:
            with self.assertRaises(HTTPException) as reused:
                auth.refresh(
                    auth.RefreshRequest(refresh_token=tokens.refresh_token),
                    DummyRequest(),
                    Response(),
                    db,
                )
        self.assertEqual(reused.exception.status_code, 401)

    def test_expired_refresh_token_is_rejected(self):
        self._register("expired-refresh@example.com")
        tokens = self._login("expired-refresh@example.com")

        expired_refresh = jwt.encode(
            {
                "sub": "1",
                "type": "refresh",
                "jti": "expired-refresh-test",
                "iat": datetime.now(timezone.utc) - timedelta(days=2),
                "nbf": datetime.now(timezone.utc) - timedelta(days=2),
                "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
                "iss": JWT_ISSUER,
            },
            SECRET_KEY,
            algorithm=ALGORITHM,
        )

        with self.Session() as db:
            with self.assertRaises(HTTPException) as context:
                auth.refresh(
                    auth.RefreshRequest(refresh_token=expired_refresh),
                    DummyRequest(),
                    Response(),
                    db,
                )
        self.assertEqual(context.exception.status_code, 401)
        self.assertTrue(tokens.refresh_token)

    def test_logout_revokes_access_and_refresh_tokens(self):
        self._register("alice@example.com")
        tokens = self._login("alice@example.com")

        logout = auth.logout(
            DummyRequest(),
            Response(),
            auth.RefreshRequest(refresh_token=tokens.refresh_token),
            self._access_credentials(tokens),
        )
        self.assertTrue(logout["message"])

        with self.Session() as db:
            with self.assertRaises(HTTPException):
                auth.get_current_user(self._access_credentials(tokens), db)

            with self.assertRaises(HTTPException) as revoked_refresh:
                auth.refresh(
                    auth.RefreshRequest(refresh_token=tokens.refresh_token),
                    DummyRequest(),
                    Response(),
                    db,
                )
        self.assertEqual(revoked_refresh.exception.status_code, 401)

    def test_login_is_rate_limited(self):
        self._register("alice@example.com")

        for _ in range(5):
            with self.Session() as db:
                with self.assertRaises(HTTPException) as failed:
                    auth.login(
                        auth.LoginRequest(
                            email="alice@example.com",
                            password="WrongPassword!2026",
                        ),
                        DummyRequest(),
                        Response(),
                        db,
                    )
                self.assertEqual(failed.exception.status_code, 401)

        with self.Session() as db:
            with self.assertRaises(HTTPException) as limited:
                auth.login(
                    auth.LoginRequest(
                        email="alice@example.com",
                        password="WrongPassword!2026",
                    ),
                    DummyRequest(),
                    Response(),
                    db,
                )
        self.assertEqual(limited.exception.status_code, 429)
        self.assertIn("Retry-After", limited.exception.headers)

    def test_cross_user_resources_are_isolated(self):
        self._register("alice@example.com")
        self._register("bob@example.com")
        alice = self._user("alice@example.com")
        bob = self._user("bob@example.com")

        with self.Session() as db:
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

            bob_workspace = CodeWorkspace(
                user_id=bob.id,
                problem_id=problem_one.id,
                language="Python",
                code="print('bob-private-code')",
            )
            bob_attempt = CodingAttempt(
                user_id=bob.id,
                problem_id=problem_one.id,
                language="Python",
                mode="submit",
                code="print('bob-submission')",
                status="Accepted",
                summary="1/1 tests passed.",
                results=[],
            )
            alice_attempt = CodingAttempt(
                user_id=alice.id,
                problem_id=problem_two.id,
                language="Python",
                mode="submit",
                code="print('alice-submission')",
                status="Accepted",
                summary="1/1 tests passed.",
                results=[],
            )
            bob_profile = UserProfile(
                user_id=bob.id,
                full_name="Bob",
                preferred_language="Python",
                experience_level="Beginner",
                target_role="Backend Engineer",
            )
            bob_session = MentorSession(
                user_id=bob.id,
                scope="practice",
                problem_id=problem_one.id,
                title="Bob's private session",
            )
            db.add_all(
                [
                    bob_workspace,
                    bob_attempt,
                    alice_attempt,
                    bob_profile,
                    bob_session,
                ]
            )
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

            workspace_result = workspace.get_workspace(
                "problem-one", "Python", alice, db
            )
            self.assertIsNone(workspace_result["code"])
            self.assertEqual(
                workspace.get_workspace(
                    "problem-one", "Python", bob, db
                )["code"],
                "print('bob-private-code')",
            )

            self.assertEqual(
                workspace.workspace_history("problem-one", 20, alice, db)["items"],
                [],
            )

            with self.assertRaises(HTTPException) as mentor_access:
                mentor.get_session(bob_session_id, alice, db)
            self.assertEqual(mentor_access.exception.status_code, 404)

            with self.assertRaises(HTTPException) as mentor_delete:
                mentor.delete_session(bob_session_id, alice, db)
            self.assertEqual(mentor_delete.exception.status_code, 404)

            alice_profile = profile.get_profile(alice, db)
            self.assertIsNone(alice_profile.full_name)

            analytics_summary = analytics.analytics_summary(
                "UTC", alice, db
            )
            self.assertEqual(analytics_summary["total_attempts"], 1)

            catalog = [
                {
                    "id": problem_one.id,
                    "slug": problem_one.slug,
                    "title": problem_one.title,
                    "difficulty": "Easy",
                    "topics": ["Arrays & Strings"],
                    "source": "local",
                    "external_id": None,
                    "external_url": None,
                    "execution_mode": "stdio",
                },
                {
                    "id": problem_two.id,
                    "slug": problem_two.slug,
                    "title": problem_two.title,
                    "difficulty": "Easy",
                    "topics": ["Binary Search"],
                    "source": "local",
                    "external_id": None,
                    "external_url": None,
                    "execution_mode": "stdio",
                },
            ]
            with patch(
                "backend.routers.recommendations._catalog_rows",
                return_value=catalog,
            ):
                recommendation = recommendations.next_recommendation(
                    None, alice, db
                )
            self.assertEqual(
                recommendation["problem"]["id"],
                problem_one.id,
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

    def test_cors_configuration_rejects_wildcards_and_invalid_origins(self):
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

        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "JWT_SECRET_KEY": "x" * 32,
                "CORS_ORIGINS": "https://example.com/app",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "paths"):
                security.get_cors_origins()


if __name__ == "__main__":
    unittest.main()
