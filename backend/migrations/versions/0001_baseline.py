"""baseline CodeMentor-AI database schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "problems",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("difficulty", sa.String(length=30), nullable=False),
        sa.Column("topics", JSON_TYPE, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("constraints", JSON_TYPE, nullable=False),
        sa.Column("examples", JSON_TYPE, nullable=False),
        sa.Column("test_cases", JSON_TYPE, nullable=False),
        sa.Column("starter_code", JSON_TYPE, nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=True),
        sa.Column("external_url", sa.String(length=500), nullable=True),
        sa.Column("execution_mode", sa.String(length=20), nullable=False),
        sa.Column("time_limit_ms", sa.Integer(), nullable=False),
        sa.Column("memory_limit_mb", sa.Integer(), nullable=True),
        sa.Column("validation", sa.String(length=30), nullable=False),
        sa.Column("package_metadata", JSON_TYPE, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("leetcode_username", sa.String(length=100), nullable=True),
        sa.Column("preferred_language", sa.String(length=50), nullable=True),
        sa.Column("experience_level", sa.String(length=50), nullable=True),
        sa.Column("target_role", sa.String(length=100), nullable=True),
        sa.Column("bio", sa.String(length=180), nullable=True),
        sa.Column("target_companies", JSON_TYPE, nullable=True),
        sa.Column("preparation_timeline", sa.String(length=100), nullable=True),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_profiles_user_id", ondelete="CASCADE"
        ),
    )
    op.create_table(
        "code_workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=50), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_code_workspaces_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["problem_id"], ["problems.id"], name="fk_code_workspaces_problem_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "problem_id", "language", name="uq_code_workspace_user_problem_language"
        ),
    )
    op.create_table(
        "coding_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("results", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_coding_attempts_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["problem_id"], ["problems.id"], name="fk_coding_attempts_problem_id", ondelete="CASCADE"
        ),
    )
    op.create_table(
        "mentor_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=True),
        sa.Column("scope", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_mentor_sessions_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["problem_id"], ["problems.id"], name="fk_mentor_sessions_problem_id", ondelete="CASCADE"
        ),
    )
    op.create_table(
        "mentor_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=True),
        sa.Column("hint_level", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["mentor_sessions.id"], name="fk_mentor_messages_session_id", ondelete="CASCADE"
        ),
    )

    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_user_profiles_user_id", "user_profiles", ["user_id"], unique=True)
    op.create_index("ix_problems_slug", "problems", ["slug"], unique=True)
    op.create_index("ix_problems_external_id", "problems", ["external_id"])
    op.create_index("ix_code_workspaces_problem_id", "code_workspaces", ["problem_id"])
    op.create_index("ix_coding_attempts_problem_id", "coding_attempts", ["problem_id"])
    op.create_index("ix_mentor_sessions_problem_id", "mentor_sessions", ["problem_id"])


def downgrade() -> None:
    op.drop_index("ix_mentor_sessions_problem_id", table_name="mentor_sessions")
    op.drop_index("ix_coding_attempts_problem_id", table_name="coding_attempts")
    op.drop_index("ix_code_workspaces_problem_id", table_name="code_workspaces")
    op.drop_index("ix_problems_external_id", table_name="problems")
    op.drop_index("ix_problems_slug", table_name="problems")
    op.drop_index("ix_user_profiles_user_id", table_name="user_profiles")
    op.drop_index("ix_users_email", table_name="users")
    for table in [
        "mentor_messages",
        "mentor_sessions",
        "coding_attempts",
        "code_workspaces",
        "user_profiles",
        "problems",
        "users",
    ]:
        op.drop_table(table)
