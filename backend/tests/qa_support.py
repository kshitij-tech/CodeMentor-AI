
from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.database import Base, get_db
from backend.models import (
    CodeWorkspace,
    CodingAttempt,
    MentorMessage,
    MentorSession,
    Problem,
    User,
    UserProfile,
)
from backend.routers.analytics import router as analytics_router
from backend.routers.auth import router as auth_router
from backend.routers.execution import router as execution_router
from backend.routers.mentor import router as mentor_router
from backend.routers.problems import router as problems_router
from backend.routers.profile import router as profile_router
from backend.routers.recommendations import router as recommendations_router
from backend.routers.workspace import router as workspace_router
from backend.security import create_access_token, hash_password
from backend.routers.problems import _catalog_cache


@dataclass
class ASGIResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes

    @property
    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


class SyncASGIClient:
    """Tiny dependency-free ASGI client for integration tests.

    It exercises FastAPI routing/dependencies without requiring TestClient/httpx.
    """

    def __init__(self, app: FastAPI):
        self.app = app

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> ASGIResponse:
        from urllib.parse import urlsplit

        parsed = urlsplit(path)
        body = b""
        request_headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("content-type", "application/json")
        request_headers.setdefault("content-length", str(len(body)))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": parsed.path or "/",
            "raw_path": (parsed.path or "/").encode("utf-8"),
            "query_string": parsed.query.encode("utf-8"),
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in request_headers.items()
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        }

        messages: list[dict[str, Any]] = []
        sent_request = False

        async def receive() -> dict[str, Any]:
            nonlocal sent_request
            if sent_request:
                return {"type": "http.disconnect"}
            sent_request = True
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        async def invoke() -> None:
            await self.app(scope, receive, send)

        asyncio.run(invoke())

        response_start = next(
            item for item in messages if item["type"] == "http.response.start"
        )
        response_body = b"".join(
            item.get("body", b"")
            for item in messages
            if item["type"] == "http.response.body"
        )
        response_headers = {
            key.decode("latin-1"): value.decode("latin-1")
            for key, value in response_start.get("headers", [])
        }
        return ASGIResponse(
            status_code=response_start["status"],
            headers=response_headers,
            body=response_body,
        )


class TestDatabase:
    def __init__(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="codementor-qa-")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={
                "check_same_thread": False,
                "timeout": 5,
            },
        )

        @event.listens_for(self.engine, "connect")
        def _configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA busy_timeout = 5000")
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.execute("PRAGMA synchronous = NORMAL")
            finally:
                cursor.close()

        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def session(self) -> Session:
        return self.session_factory()

    def close(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()


def build_test_app(database: TestDatabase) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(problems_router)
    app.include_router(execution_router)
    app.include_router(mentor_router)
    app.include_router(analytics_router)
    app.include_router(recommendations_router)
    app.include_router(workspace_router)

    def override_get_db():
        db = database.session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return app


def reset_catalog_cache() -> None:
    _catalog_cache.update(
        {
            "loaded_at": 0.0,
            "rows": [],
            "topics": [],
            "difficulties": [],
            "total": 0,
        }
    )


def add_user(
    db: Session,
    email: str,
    password: str = "password123",
) -> User:
    user = User(
        email=email.strip().lower(),
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_token(user: User) -> str:
    return create_access_token(str(user.id))


def auth_headers(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def add_problem(
    db: Session,
    *,
    slug: str,
    title: str = "Two Sum",
    difficulty: str = "Easy",
    topics: list[str] | None = None,
    description: str = "Given input values, calculate the expected answer.",
    test_cases: list[dict[str, Any]] | None = None,
    source: str = "qa",
    package_metadata: dict[str, Any] | None = None,
) -> Problem:
    problem = Problem(
        slug=slug,
        title=title,
        difficulty=difficulty,
        topics=topics or ["Arrays & Strings"],
        description=description,
        constraints=[],
        examples=[{"input": "2", "output": "4"}],
        test_cases=test_cases
        or [
            {
                "input": "2\n",
                "expected_output": "4\n",
                "visibility": "sample",
            }
        ],
        starter_code={"Python": "import sys\nprint(int(sys.stdin.read()) * 2)\n"},
        source=source,
        external_id=None,
        external_url=None,
        execution_mode="stdio",
        time_limit_ms=1000,
        memory_limit_mb=256,
        validation="default",
        package_metadata=package_metadata,
    )
    db.add(problem)
    db.commit()
    db.refresh(problem)
    return problem


def add_profile(
    db: Session,
    user_id: int,
    *,
    experience_level: str = "Beginner",
    target_role: str = "Software Engineer",
) -> UserProfile:
    profile = UserProfile(
        user_id=user_id,
        full_name="QA User",
        preferred_language="Python",
        experience_level=experience_level,
        target_role=target_role,
        target_companies=["Acme"],
        preparation_timeline="8 weeks",
        onboarding_completed=True,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def add_attempt(
    db: Session,
    *,
    user_id: int,
    problem_id: int,
    status: str = "Accepted",
    mode: str = "submit",
    created_at=None,
    language: str = "Python",
    runtime_ms: int = 25,
    code: str = "print(42)",
) -> CodingAttempt:
    attempt = CodingAttempt(
        user_id=user_id,
        problem_id=problem_id,
        language=language,
        mode=mode,
        code=code,
        status=status,
        summary=f"{status} QA fixture",
        results=[{"runtime_ms": runtime_ms, "status": status}],
        created_at=created_at,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def add_mentor_session(
    db: Session,
    *,
    user_id: int,
    problem_id: int | None = None,
    scope: str = "practice",
) -> MentorSession:
    session = MentorSession(
        user_id=user_id,
        problem_id=problem_id,
        scope=scope,
        title="QA Mentor Session",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def add_mentor_message(
    db: Session,
    *,
    session_id: int,
    role: str,
    content: str,
    action: str | None = None,
    hint_level: int | None = 1,
) -> MentorMessage:
    message = MentorMessage(
        session_id=session_id,
        role=role,
        content=content,
        action=action,
        hint_level=hint_level,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


__all__ = [
    "ASGIResponse",
    "SyncASGIClient",
    "TestDatabase",
    "User",
    "Problem",
    "CodeWorkspace",
    "CodingAttempt",
    "MentorSession",
    "MentorMessage",
    "build_test_app",
    "reset_catalog_cache",
    "add_user",
    "auth_token",
    "auth_headers",
    "add_problem",
    "add_profile",
    "add_attempt",
    "add_mentor_session",
    "add_mentor_message",
]
