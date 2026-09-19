from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        index=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    full_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    leetcode_username: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    preferred_language: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    experience_level: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    target_role: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    bio: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True,
    )
    target_companies: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    preparation_timeline: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    onboarding_completed: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(30), nullable=False)
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    examples: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    test_cases: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    starter_code: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class CodingAttempt(Base):
    __tablename__ = "coding_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
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
    results: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class MentorSession(Base):
    __tablename__ = "mentor_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
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

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("mentor_sessions.id", ondelete="CASCADE"),
        index=True,
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
