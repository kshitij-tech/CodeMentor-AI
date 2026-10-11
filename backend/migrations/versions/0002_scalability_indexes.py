"""add workload-specific indexes for high-volume queries

Revision ID: 0002_scalability_indexes
Revises: 0001_baseline
Create Date: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_scalability_indexes"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_index(name: str, table: str, columns: list[str]) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            op.create_index(
                name,
                table,
                columns,
                postgresql_concurrently=True,
            )
    else:
        op.create_index(name, table, columns)


def upgrade() -> None:
    # Remove redundant single-column indexes from the pre-scalability schema.
    # Keep FK-side problem_id indexes because parent deletes use them.
    for index_name in [
        "ix_users_id",
        "ix_user_profiles_id",
        "ix_code_workspaces_id",
        "ix_code_workspaces_user_id",
        "ix_coding_attempts_id",
        "ix_coding_attempts_user_id",
        "ix_mentor_sessions_id",
        "ix_mentor_sessions_user_id",
        "ix_mentor_messages_id",
        "ix_mentor_messages_session_id",
    ]:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {index_name}"))

    _create_index(
        "ix_problems_source_external_id",
        "problems",
        ["source", "external_id"],
    )
    _create_index(
        "ix_problems_difficulty_id",
        "problems",
        ["difficulty", "id"],
    )
    _create_index(
        "ix_code_workspaces_user_updated_at",
        "code_workspaces",
        ["user_id", "updated_at"],
    )
    _create_index(
        "ix_coding_attempts_user_created_at",
        "coding_attempts",
        ["user_id", "created_at", "id"],
    )
    _create_index(
        "ix_coding_attempts_user_problem_created_at",
        "coding_attempts",
        ["user_id", "problem_id", "created_at", "id"],
    )
    _create_index(
        "ix_coding_attempts_user_mode_status_created_at",
        "coding_attempts",
        ["user_id", "mode", "status", "created_at"],
    )
    _create_index(
        "ix_mentor_sessions_user_scope_problem_updated_at",
        "mentor_sessions",
        ["user_id", "scope", "problem_id", "updated_at", "id"],
    )
    _create_index(
        "ix_mentor_messages_session_created_at",
        "mentor_messages",
        ["session_id", "created_at", "id"],
    )
    _create_index(
        "ix_mentor_messages_session_role_action",
        "mentor_messages",
        ["session_id", "role", "action", "created_at"],
    )


def downgrade() -> None:
    for name in [
        "ix_mentor_messages_session_role_action",
        "ix_mentor_messages_session_created_at",
        "ix_mentor_sessions_user_scope_problem_updated_at",
        "ix_coding_attempts_user_mode_status_created_at",
        "ix_coding_attempts_user_problem_created_at",
        "ix_coding_attempts_user_created_at",
        "ix_code_workspaces_user_updated_at",
        "ix_problems_difficulty_id",
        "ix_problems_source_external_id",
    ]:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
