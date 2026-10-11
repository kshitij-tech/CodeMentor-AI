
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.models import (
    CodeWorkspace,
    CodingAttempt,
    MentorMessage,
    MentorSession,
    User,
    UserProfile,
)
from backend.tests.qa_support import TestDatabase, add_problem, add_user


class DatabaseQualityTests(unittest.TestCase):
    def setUp(self):
        self.database = TestDatabase()
        self.db = self.database.session()

    def tearDown(self):
        self.db.close()
        self.database.close()

    def test_sqlite_pragmas_are_configured_for_concurrency(self):
        busy_timeout = self.db.execute(text("PRAGMA busy_timeout")).scalar_one()
        journal_mode = self.db.execute(text("PRAGMA journal_mode")).scalar_one()
        synchronous = self.db.execute(text("PRAGMA synchronous")).scalar_one()

        self.assertGreaterEqual(busy_timeout, 5000)
        self.assertEqual(str(journal_mode).lower(), "wal")
        self.assertIn(synchronous, (1, 2))

    def test_unique_constraints_reject_duplicate_email_and_workspace(self):
        user = add_user(self.db, "unique@example.com")
        problem = add_problem(self.db, slug="unique-problem")

        self.db.add(User(email="unique@example.com", password_hash="x"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        workspace = CodeWorkspace(
            user_id=user.id,
            problem_id=problem.id,
            language="Python",
            code="print(1)",
        )
        duplicate = CodeWorkspace(
            user_id=user.id,
            problem_id=problem.id,
            language="Python",
            code="print(2)",
        )
        self.db.add_all([workspace, duplicate])
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        self.assertEqual(self.db.query(CodeWorkspace).count(), 0)

    def test_user_delete_cascades_user_owned_rows(self):
        user = add_user(self.db, "cascade@example.com")
        problem = add_problem(self.db, slug="cascade-problem")

        self.db.add(UserProfile(user_id=user.id, full_name="Cascade"))
        workspace = CodeWorkspace(
            user_id=user.id,
            problem_id=problem.id,
            language="Python",
            code="print(1)",
        )
        self.db.add(workspace)
        attempt = CodingAttempt(
            user_id=user.id,
            problem_id=problem.id,
            language="Python",
            mode="submit",
            code="print(1)",
            status="Accepted",
            summary="accepted",
            results=[],
        )
        self.db.add(attempt)
        session = MentorSession(
            user_id=user.id,
            problem_id=problem.id,
            scope="practice",
            title="Cascade",
        )
        self.db.add(session)
        self.db.flush()
        self.db.add(
            MentorMessage(
                session_id=session.id,
                role="user",
                content="hello",
            )
        )
        self.db.commit()

        self.db.delete(user)
        self.db.commit()

        self.assertEqual(
            self.db.query(UserProfile).filter_by(user_id=user.id).count(),
            0,
        )
        self.assertEqual(
            self.db.query(CodeWorkspace).filter_by(user_id=user.id).count(),
            0,
        )
        self.assertEqual(
            self.db.query(CodingAttempt).filter_by(user_id=user.id).count(),
            0,
        )
        self.assertEqual(
            self.db.query(MentorSession).filter_by(user_id=user.id).count(),
            0,
        )
        self.assertEqual(self.db.query(MentorMessage).count(), 0)
        self.assertEqual(self.db.query(User).filter_by(id=user.id).count(), 0)

    def test_rollback_does_not_leak_failed_transaction(self):
        pending = User(
            email="rollback@example.com",
            password_hash="x",
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(pending)
        self.db.rollback()

        self.assertIsNone(
            self.db.query(User).filter_by(email="rollback@example.com").first()
        )

    def test_concurrent_writes_complete_without_sqlite_lock_errors(self):
        def write_problem(index):
            session = self.database.session()
            try:
                problem = add_problem(
                    session,
                    slug=f"concurrent-{index}",
                    title=f"Concurrent {index}",
                )
                return problem.id
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(write_problem, range(12)))

        self.assertEqual(len(results), 12)
        self.assertEqual(len(set(results)), 12)
        self.assertEqual(self.db.query(User).count(), 0)
        self.assertEqual(self.db.query(CodeWorkspace).count(), 0)

    def test_busy_timeout_allows_writer_to_wait_for_short_lock(self):
        holder = self.database.session()
        holder.execute(text("BEGIN IMMEDIATE"))

        finished = threading.Event()
        outcome = {}

        def writer():
            session = self.database.session()
            try:
                session.add(
                    User(
                        email="waiting@example.com",
                        password_hash="x",
                    )
                )
                session.commit()
                outcome["committed"] = True
            except Exception as exc:
                session.rollback()
                outcome["error"] = exc
            finally:
                session.close()
                finished.set()

        thread = threading.Thread(target=writer)
        thread.start()
        time.sleep(0.2)

        self.assertFalse(
            finished.is_set(),
            "Writer should still be waiting on the held SQLite write lock.",
        )

        holder.commit()
        thread.join(timeout=5)

        self.assertTrue(finished.is_set(), "Writer did not finish after lock release.")
        self.assertNotIn("error", outcome, repr(outcome.get("error")))
        self.assertTrue(outcome.get("committed"))

        self.assertIsNotNone(
            self.db.query(User)
            .filter_by(email="waiting@example.com")
            .first()
        )

        holder.close()


if __name__ == "__main__":
    unittest.main()
