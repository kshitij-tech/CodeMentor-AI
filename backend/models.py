from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


POSTGRES_JSON = JSON().with_variant(JSONB(), "postgresql")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        index=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (Index("ix_user_profiles_user_id", "user_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    leetcode_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    experience_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(180), nullable=True)
    target_companies: Mapped[list[str] | None] = mapped_column(POSTGRES_JSON, nullable=True)
    preparation_timeline: Mapped[str | None] = mapped_column(String(100), nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Problem(Base):
    __tablename__ = "problems"
    __table_args__ = (
        Index("ix_problems_slug", "slug", unique=True),
        Index("ix_problems_source_external_id", "source", "external_id"),
        Index("ix_problems_difficulty_id", "difficulty", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(30), nullable=False)
    topics: Mapped[list[str]] = mapped_column(POSTGRES_JSON, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[list[str]] = mapped_column(POSTGRES_JSON, nullable=False)
    examples: Mapped[list[dict]] = mapped_column(POSTGRES_JSON, nullable=False)
    test_cases: Mapped[list[dict]] = mapped_column(POSTGRES_JSON, nullable=False, default=list)
    starter_code: Mapped[dict[str, str]] = mapped_column(POSTGRES_JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="local")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="function")
    time_limit_ms: Mapped[int] = mapped_column(nullable=False, default=2000)
    memory_limit_mb: Mapped[int | None] = mapped_column(nullable=True)
    validation: Mapped[str] = mapped_column(String(30), nullable=False, default="default")
    package_metadata: Mapped[dict | None] = mapped_column(POSTGRES_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class CodeWorkspace(Base):
    __tablename__ = "code_workspaces"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "problem_id",
            "language",
            name="uq_code_workspace_user_problem_language",
        ),
        Index(
            "ix_code_workspaces_user_updated_at",
            "user_id",
            "updated_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[int] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class CodingAttempt(Base):
    __tablename__ = "coding_attempts"
    __table_args__ = (
        Index(
            "ix_coding_attempts_user_created_at",
            "user_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_coding_attempts_user_problem_created_at",
            "user_id",
            "problem_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_coding_attempts_user_mode_status_created_at",
            "user_id",
            "mode",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[int] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(50), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    results: Mapped[list[dict]] = mapped_column(POSTGRES_JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class MentorSession(Base):
    __tablename__ = "mentor_sessions"
    __table_args__ = (
        Index(
            "ix_mentor_sessions_user_scope_problem_updated_at",
            "user_id",
            "scope",
            "problem_id",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[int | None] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    scope: Mapped[str] = mapped_column(String(30), nullable=False, default="practice")
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class MentorMessage(Base):
    __tablename__ = "mentor_messages"
    __table_args__ = (
        Index(
            "ix_mentor_messages_session_created_at",
            "session_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_mentor_messages_session_role_action",
            "session_id",
            "role",
            "action",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("mentor_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hint_level: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
