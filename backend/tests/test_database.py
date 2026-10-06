import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.schema import CreateTable
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.database import (
    Base,
    is_retryable_concurrency_error,
    normalize_database_url,
    run_in_transaction,
    session_scope,
)
from backend.database_pagination import decode_cursor, encode_cursor, keyset_paginate
from backend.database_retention import RetentionPolicy, purge_expired_activity
from backend.models import (
    CodingAttempt,
    CodeWorkspace,
    MentorMessage,
    MentorSession,
    Problem,
    User,
    UserProfile,
)


class DatabaseSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def setUp(self):
        with Session(self.engine) as db:
            for model in (
                MentorMessage,
                MentorSession,
                CodingAttempt,
                CodeWorkspace,
                UserProfile,
                Problem,
                User,
            ):
                db.query(model).delete(synchronize_session=False)
            db.commit()

    def test_required_composite_indexes_exist(self):
        index_map = {
            table.name: {index["name"] for index in inspect(self.engine).get_indexes(table.name)}
            for table in Base.metadata.sorted_tables
        }
        expected = {
            "problems": {"ix_problems_source_external_id", "ix_problems_difficulty_id"},
            "code_workspaces": {"ix_code_workspaces_user_updated_at"},
            "coding_attempts": {
                "ix_coding_attempts_user_created_at",
                "ix_coding_attempts_user_problem_created_at",
                "ix_coding_attempts_user_mode_status_created_at",
            },
            "mentor_sessions": {"ix_mentor_sessions_user_scope_problem_updated_at"},
            "mentor_messages": {
                "ix_mentor_messages_session_created_at",
                "ix_mentor_messages_session_role_action",
            },
        }
        for table, names in expected.items():
            self.assertTrue(names.issubset(index_map[table]), (table, index_map[table]))

    def test_foreign_keys_are_declared(self):
        for table_name in [
            "user_profiles",
            "code_workspaces",
            "coding_attempts",
            "mentor_sessions",
            "mentor_messages",
        ]:
            foreign_keys = inspect(self.engine).get_foreign_keys(table_name)
            self.assertTrue(foreign_keys, table_name)
            self.assertTrue(
                all(fk["options"].get("ondelete") == "CASCADE" for fk in foreign_keys)
            )

    def test_user_delete_cascades_user_owned_data(self):
        with Session(self.engine) as db:
            user = User(email="cascade@example.com", password_hash="x")
            problem = Problem(
                slug="cascade-problem",
                title="Cascade",
                difficulty="Easy",
                topics=["Arrays"],
                description="x",
                constraints=[],
                examples=[],
                test_cases=[],
                starter_code={},
            )
            db.add_all([user, problem])
            db.flush()
            db.add_all(
                [
                    UserProfile(user_id=user.id),
                    CodeWorkspace(
                        user_id=user.id,
                        problem_id=problem.id,
                        language="Python",
                        code="x",
                    ),
                    CodingAttempt(
                        user_id=user.id,
                        problem_id=problem.id,
                        language="Python",
                        mode="submit",
                        code="x",
                        status="Accepted",
                        summary="ok",
                        results=[],
                    ),
                    MentorSession(
                        user_id=user.id,
                        problem_id=problem.id,
                        scope="practice",
                        title="x",
                    ),
                ]
            )
            db.flush()
            session = db.query(MentorSession).one()
            db.add(MentorMessage(session_id=session.id, role="user", content="x"))
            db.commit()

            db.delete(user)
            db.commit()

            self.assertEqual(db.query(UserProfile).count(), 0)
            self.assertEqual(db.query(CodeWorkspace).count(), 0)
            self.assertEqual(db.query(CodingAttempt).count(), 0)
            self.assertEqual(db.query(MentorSession).count(), 0)
            self.assertEqual(db.query(MentorMessage).count(), 0)

    def test_problem_delete_cascades_problem_owned_data(self):
        with Session(self.engine) as db:
            user = User(email="problem-cascade@example.com", password_hash="x")
            problem = Problem(
                slug="problem-cascade",
                title="Cascade",
                difficulty="Easy",
                topics=["Arrays"],
                description="x",
                constraints=[],
                examples=[],
                test_cases=[],
                starter_code={},
            )
            db.add_all([user, problem])
            db.flush()
            workspace = CodeWorkspace(
                user_id=user.id, problem_id=problem.id, language="Python", code="x"
            )
            attempt = CodingAttempt(
                user_id=user.id,
                problem_id=problem.id,
                language="Python",
                mode="submit",
                code="x",
                status="Accepted",
                summary="ok",
                results=[],
            )
            session = MentorSession(
                user_id=user.id, problem_id=problem.id, scope="practice", title="x"
            )
            db.add_all([workspace, attempt, session])
            db.flush()
            db.add(MentorMessage(session_id=session.id, role="assistant", content="x"))
            db.commit()

            db.delete(problem)
            db.commit()

            self.assertEqual(db.query(CodeWorkspace).count(), 0)
            self.assertEqual(db.query(CodingAttempt).count(), 0)
            self.assertEqual(db.query(MentorSession).count(), 0)
            self.assertEqual(db.query(MentorMessage).count(), 0)

    def test_foreign_key_violation_is_rejected(self):
        with Session(self.engine) as db:
            db.add(
                CodingAttempt(
                    user_id=999999,
                    problem_id=999999,
                    language="Python",
                    mode="submit",
                    code="x",
                    status="Accepted",
                    summary="invalid",
                    results=[],
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_postgresql_url_is_normalized_to_psycopg3(self):
        self.assertEqual(
            normalize_database_url("postgres://user:pass@db.example/app"),
            "postgresql+psycopg://user:pass@db.example/app",
        )
        self.assertEqual(
            normalize_database_url("postgresql://user:pass@db.example/app"),
            "postgresql+psycopg://user:pass@db.example/app",
        )

    def test_postgresql_uses_jsonb_for_document_columns(self):
        sql = str(CreateTable(Problem.__table__).compile(dialect=postgresql.dialect()))
        self.assertIn("JSONB", sql)

    def test_analytics_query_uses_user_created_at_index(self):
        with Session(self.engine) as db:
            user = User(email="plan@example.com", password_hash="x")
            problem = Problem(
                slug="plan-problem",
                title="Plan",
                difficulty="Medium",
                topics=["Arrays"],
                description="x",
                constraints=[],
                examples=[],
                test_cases=[],
                starter_code={},
            )
            db.add_all([user, problem])
            db.flush()
            db.bulk_save_objects(
                [
                    CodingAttempt(
                        user_id=user.id,
                        problem_id=problem.id,
                        language="Python",
                        mode="submit",
                        code="x",
                        status="Accepted",
                        summary="x",
                        results=[],
                        created_at=datetime.now(timezone.utc) + timedelta(seconds=i),
                    )
                    for i in range(100)
                ]
            )
            db.commit()
            plan = db.execute(
                text(
                    "EXPLAIN QUERY PLAN "
                    "SELECT id FROM coding_attempts "
                    "WHERE user_id = :user_id "
                    "ORDER BY created_at, id LIMIT 10"
                ),
                {"user_id": user.id},
            ).all()
            plan_text = " ".join(str(row[-1]) for row in plan)
            self.assertIn("ix_coding_attempts_user_created_at", plan_text)


class DatabaseTransactionTests(unittest.TestCase):
    def test_session_scope_rolls_back_on_error(self):
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with session_scope() as db:
                db.add(User(email="rollback@example.com", password_hash="x"))
                raise RuntimeError("boom")

    def test_run_in_transaction_commits_once(self):
        result = run_in_transaction(
            lambda db: db.execute(text("SELECT 1")).scalar_one()
        )
        self.assertEqual(result, 1)

    def test_retryable_concurrency_detection(self):
        sqlite_error = OperationalError(
            "UPDATE", {}, RuntimeError("database is locked")
        )
        self.assertTrue(is_retryable_concurrency_error(sqlite_error))


class PaginationTests(unittest.TestCase):
    def test_cursor_round_trip(self):
        value = datetime(2026, 10, 6, 12, 34, 56, tzinfo=timezone.utc)
        cursor = encode_cursor(value, 42)
        decoded_time, decoded_id = decode_cursor(cursor)
        self.assertEqual(decoded_time, value)
        self.assertEqual(decoded_id, 42)

    def test_keyset_returns_stable_pages(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(email="page@example.com", password_hash="x")
            problem = Problem(
                slug="page-problem",
                title="Page",
                difficulty="Easy",
                topics=["Arrays"],
                description="x",
                constraints=[],
                examples=[],
                test_cases=[],
                starter_code={},
            )
            db.add_all([user, problem])
            db.flush()
            base = datetime(2026, 1, 1, tzinfo=timezone.utc)
            db.add_all(
                [
                    CodingAttempt(
                        user_id=user.id,
                        problem_id=problem.id,
                        language="Python",
                        mode="submit",
                        code=str(i),
                        status="Accepted",
                        summary="x",
                        results=[],
                        created_at=base + timedelta(seconds=i),
                    )
                    for i in range(5)
                ]
            )
            db.commit()

            page1 = keyset_paginate(
                db.query(CodingAttempt),
                created_at_column=CodingAttempt.created_at,
                id_column=CodingAttempt.id,
                limit=2,
            )
            page2 = keyset_paginate(
                db.query(CodingAttempt),
                created_at_column=CodingAttempt.created_at,
                id_column=CodingAttempt.id,
                limit=2,
                cursor=page1.next_cursor,
            )
            self.assertEqual([row.code for row in page1.items], ["4", "3"])
            self.assertEqual([row.code for row in page2.items], ["2", "1"])
            self.assertTrue(page1.has_more)
            self.assertTrue(page2.has_more)


class RetentionTests(unittest.TestCase):
    def test_retention_deletes_only_expired_activity(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(email="retention@example.com", password_hash="x")
            problem = Problem(
                slug="retention-problem",
                title="Retention",
                difficulty="Easy",
                topics=["Arrays"],
                description="x",
                constraints=[],
                examples=[],
                test_cases=[],
                starter_code={},
            )
            db.add_all([user, problem])
            db.flush()
            old = datetime.now(timezone.utc) - timedelta(days=800)
            session = MentorSession(
                user_id=user.id, problem_id=problem.id, scope="practice", title="x"
            )
            db.add_all(
                [
                    CodingAttempt(
                        user_id=user.id,
                        problem_id=problem.id,
                        language="Python",
                        mode="submit",
                        code="old",
                        status="Wrong Answer",
                        summary="old",
                        results=[],
                        created_at=old,
                    ),
                    session,
                ]
            )
            db.flush()
            db.add(
                MentorMessage(
                    session_id=session.id,
                    role="user",
                    content="old",
                    created_at=old,
                )
            )
            db.commit()

            counts = purge_expired_activity(
                db,
                policy=RetentionPolicy(
                    coding_attempt_days=730,
                    mentor_message_days=365,
                ),
                now=datetime.now(timezone.utc),
            )
            db.commit()
            self.assertEqual(
                counts, {"mentor_messages": 1, "coding_attempts": 1}
            )
            self.assertEqual(db.query(Problem).count(), 1)
            self.assertEqual(db.query(MentorSession).count(), 1)


if __name__ == "__main__":
    unittest.main()
