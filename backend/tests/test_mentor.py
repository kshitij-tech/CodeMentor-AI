import unittest
from unittest.mock import patch

from backend.database import Base, SessionLocal, engine
from backend.models import MentorMessage, MentorSession, Problem, User
from backend.routers.mentor import (
    CreateSessionRequest,
    DashboardMentorRequest,
    MentorRequest,
    _get_or_create_session,
    analyze,
    create_session,
    delete_session,
    get_session,
)


class MentorSessionPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.user = User(email="test@example.com", password_hash="hash")
        self.other = User(email="other@example.com", password_hash="hash")
        self.problem = Problem(
            slug="two-sum",
            title="Two Sum",
            difficulty="Easy",
            topics=["arrays"],
            description="Find two indices whose values sum to a target.",
            constraints=["2 <= n"],
            examples=[],
            test_cases=[],
            starter_code={"Python": "print(1)"},
        )
        self.db.add_all([self.user, self.other, self.problem])
        self.db.commit()
        self.db.refresh(self.user)
        self.db.refresh(self.other)
        self.db.refresh(self.problem)

    def tearDown(self):
        self.db.query(MentorMessage).delete()
        self.db.query(MentorSession).delete()
        self.db.query(Problem).delete()
        self.db.query(User).delete()
        self.db.commit()
        self.db.close()

    def test_create_session_always_creates_new_chat(self):
        first = create_session(
            CreateSessionRequest(scope="practice", problem_slug="two-sum"),
            current_user=self.user,
            db=self.db,
        )
        second = create_session(
            CreateSessionRequest(scope="practice", problem_slug="two-sum"),
            current_user=self.user,
            db=self.db,
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["problem_slug"], "two-sum")

    def test_analyze_persists_both_messages_and_reuses_session(self):
        calls = []

        def fake_mentor_response(**kwargs):
            calls.append(kwargs)
            return {"answer": "Trace line 2.", "error_line": 2, "patch": None}

        request = MentorRequest(
            problem_slug="two-sum",
            language="Python",
            code="x = 1\nprint(x)",
            action="debug",
            question="Why?",
            hint_level=1,
            execution={"status": "Wrong Answer", "error_line": 2},
        )
        with patch("backend.routers.mentor.mentor_response", side_effect=fake_mentor_response):
            first = analyze(request, current_user=self.user, db=self.db)
            second = analyze(
                request.model_copy(update={"question": "What should I inspect next?"}),
                current_user=self.user,
                db=self.db,
            )

        self.assertEqual(first["session_id"], second["session_id"])
        messages = (
            self.db.query(MentorMessage)
            .filter(MentorMessage.session_id == first["session_id"])
            .order_by(MentorMessage.id)
            .all()
        )
        self.assertEqual(len(messages), 4)
        self.assertEqual([m.role for m in messages], ["user", "assistant", "user", "assistant"])
        self.assertIn("Why?", calls[1]["history"][-2]["content"])

    def test_explicit_session_context_is_enforced(self):
        session = _get_or_create_session(
            self.db, self.user, scope="practice", problem=self.problem
        )
        self.db.commit()
        with self.assertRaises(Exception) as ctx:
            _get_or_create_session(
                self.db, self.user, scope="practice", problem=None, session_id=session.id
            )
        self.assertEqual(getattr(ctx.exception, "status_code", None), 400)

    def test_session_is_private_to_owner(self):
        session = _get_or_create_session(
            self.db, self.user, scope="practice", problem=self.problem
        )
        self.db.commit()
        with self.assertRaises(Exception) as ctx:
            get_session(session.id, current_user=self.other, db=self.db)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)

    def test_delete_session_removes_messages(self):
        session = _get_or_create_session(
            self.db, self.user, scope="practice", problem=self.problem
        )
        self.db.add(
            MentorMessage(
                session_id=session.id,
                role="user",
                content="hello",
                action="question",
                hint_level=1,
            )
        )
        self.db.commit()
        result = delete_session(session.id, current_user=self.user, db=self.db)
        self.assertTrue(result["deleted"])
        self.assertIsNone(self.db.get(MentorSession, session.id))
        self.assertEqual(self.db.query(MentorMessage).count(), 0)


class MentorRequestCompatibilityTests(unittest.TestCase):
    def test_existing_contract_is_unchanged(self):
        request = MentorRequest(
            problem_slug="two-sum",
            language="Python",
            code="print(1)",
            action="hint",
            hint_level=2,
        )
        self.assertEqual(request.action, "hint")
        self.assertEqual(request.hint_level, 2)
        self.assertIsNone(request.session_id)

    def test_dashboard_contract_accepts_session_id(self):
        request = DashboardMentorRequest(question="explain hashing", session_id=42)
        self.assertEqual(request.session_id, 42)

if __name__ == "__main__":
    unittest.main()
