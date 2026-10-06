import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest
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
from backend.problem_catalog import normalize_difficulty
from backend.routers import analytics, auth, mentor, profile, recommendations, workspace
from backend.security import (
    ALGORITHM,
    JWT_ISSUER,
    SECRET_KEY,
    create_access_token,
    reset_security_state_for_tests,
)


@pytest.fixture()
def api():
    reset_security_state_for_tests()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    for router in (
        auth.router,
        profile.router,
        workspace.router,
        mentor.router,
        analytics.router,
        recommendations.router,
    ):
        app.include_router(router)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as client:
        yield client, Session, engine

    reset_security_state_for_tests()
    engine.dispose()


def _register(client, email, password="StrongPassword!2026"):
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201, response.text


def _login(client, email, password="StrongPassword!2026"):
    response = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_registration_hashes_password_and_login_issues_access_and_refresh(api):
    client, Session, _ = api
    _register(client, "Alice@Example.com")

    with Session() as db:
        user = db.query(User).filter(User.email == "alice@example.com").one()
        assert user.password_hash != "StrongPassword!2026"
        assert user.password_hash.startswith("$argon2")

    tokens = _login(client, "alice@example.com")
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["expires_in"] > 0
    assert tokens["refresh_expires_in"] > tokens["expires_in"]

    me = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


def test_missing_invalid_and_expired_tokens_are_rejected(api):
    client, Session, _ = api
    _register(client, "alice@example.com")
    _login(client, "alice@example.com")

    assert client.get("/auth/me").status_code == 401

    malformed = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer definitely-not-a-jwt"},
    )
    assert malformed.status_code == 401
    assert malformed.headers["www-authenticate"] == "Bearer"

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
    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert response.status_code == 401


def test_refresh_rotates_token_and_rejects_reuse(api):
    client, _, _ = api
    _register(client, "alice@example.com")
    tokens = _login(client, "alice@example.com")

    refreshed = client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    refreshed_tokens = refreshed.json()
    assert refreshed_tokens["access_token"] != tokens["access_token"]
    assert refreshed_tokens["refresh_token"] != tokens["refresh_token"]

    reused = client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert reused.status_code == 401


def test_logout_revokes_access_and_refresh_tokens(api):
    client, _, _ = api
    _register(client, "alice@example.com")
    tokens = _login(client, "alice@example.com")

    logout = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert logout.status_code == 200

    assert client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    ).status_code == 401

    assert client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    ).status_code == 401


def test_login_and_registration_are_rate_limited(api):
    client, _, _ = api
    _register(client, "alice@example.com")

    for _ in range(5):
        assert client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "WrongPassword!2026"},
        ).status_code == 401

    limited = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "WrongPassword!2026"},
    )
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_cross_user_resources_are_isolated(api):
    client, Session, _ = api
    _register(client, "alice@example.com")
    _register(client, "bob@example.com")
    alice = _login(client, "alice@example.com")
    bob = _login(client, "bob@example.com")
    alice_headers = {"Authorization": f"Bearer {alice['access_token']}"}
    bob_headers = {"Authorization": f"Bearer {bob['access_token']}"}

    with Session() as db:
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

        bob_profile = UserProfile(
            user_id=bob_user.id,
            full_name="Bob",
            preferred_language="Python",
            experience_level="Beginner",
            target_role="Backend Engineer",
        )
        db.add(bob_profile)

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

    workspace_response = client.get(
        "/workspace",
        params={"problem_slug": "problem-one", "language": "Python"},
        headers=alice_headers,
    )
    assert workspace_response.status_code == 200
    assert workspace_response.json()["code"] is None

    history_response = client.get(
        "/workspace/history",
        params={"problem_slug": "problem-one"},
        headers=alice_headers,
    )
    assert history_response.status_code == 200
    assert history_response.json()["items"] == []

    mentor_response = client.get(
        f"/mentor/sessions/{bob_session_id}",
        headers=alice_headers,
    )
    assert mentor_response.status_code == 404

    profile_response = client.get("/profile", headers=alice_headers)
    assert profile_response.status_code == 200
    assert profile_response.json()["full_name"] is None

    analytics_response = client.get("/analytics/summary", headers=alice_headers)
    assert analytics_response.status_code == 200
    assert analytics_response.json()["total_attempts"] == 1

    recommendations._catalog_cache["loaded_at"] = 0.0
    recommendation_response = client.get(
        "/recommendations/next",
        headers=alice_headers,
    )
    assert recommendation_response.status_code == 200
    assert recommendation_response.json()["problem"]["id"] != 2

    # Verify Bob still sees his own private resources.
    bob_workspace = client.get(
        "/workspace",
        params={"problem_slug": "problem-one", "language": "Python"},
        headers=bob_headers,
    )
    assert bob_workspace.status_code == 200
    assert bob_workspace.json()["code"] == "print('bob-private-code')"

    bob_mentor = client.get(
        f"/mentor/sessions/{bob_session_id}",
        headers=bob_headers,
    )
    assert bob_mentor.status_code == 200
    assert bob_mentor.json()["messages"][0]["content"] == "Bob secret message"


def test_secure_configuration_rejects_insecure_production_secret(monkeypatch):
    from backend import security

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "dev-only-secret-change-me")
    monkeypatch.setenv("CORS_ORIGINS", "https://example.com")

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        security.validate_security_configuration()


def test_cors_configuration_rejects_wildcards_and_null(monkeypatch):
    from backend import security

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("CORS_ORIGINS", "*,null")

    with pytest.raises(RuntimeError, match="wildcard"):
        security.get_cors_origins()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
