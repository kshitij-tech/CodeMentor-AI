import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.career import ROLE_PROFILES, get_role, normalized_role_key, readiness_band, topic_match
from backend.database import Base
from backend.models import CodingAttempt, Problem, User, UserProfile
from backend.routers import career as career_router
from backend.routers.auth import get_current_user


class CareerCoreTests(unittest.TestCase):
    def test_role_catalog_is_modular(self):
        self.assertGreaterEqual(len(ROLE_PROFILES), 7)
        for role in ROLE_PROFILES.values():
            self.assertTrue(role.dsa_topics)
            self.assertTrue(role.cs_fundamentals)
            self.assertTrue(role.role_skills)
            self.assertTrue(role.phases)

    def test_role_aliases(self):
        self.assertEqual(normalized_role_key("Backend Developer"), "backend_developer")
        self.assertEqual(normalized_role_key("Full Stack"), "full_stack_developer")
        self.assertEqual(normalized_role_key("Data/ML"), "data_ml")
        self.assertEqual(get_role("").key, "software_engineer")

    def test_topic_and_readiness_helpers(self):
        self.assertTrue(topic_match("Arrays & Strings", "Arrays & Strings"))
        self.assertTrue(topic_match("Arrays and Strings", "Arrays & Strings"))
        self.assertEqual(readiness_band(90), "Interview ready")
        self.assertEqual(readiness_band(45), "Building foundations")


class CareerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False, autocommit=False)
        Base.metadata.create_all(cls.engine)
        db = cls.SessionLocal()
        user = User(email="career@example.com", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(UserProfile(
            user_id=user.id,
            target_role="software_engineer",
            target_companies=["Google"],
        ))
        db.commit()
        cls.user_id = user.id
        cls.db = db
        cls.user = user

        app = FastAPI()
        app.include_router(career_router.router)
        app.dependency_overrides[career_router.get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.user
        cls.client = TestClient(app)

    def setUp(self):
        profile = self.db.query(UserProfile).filter(UserProfile.user_id == self.user_id).first()
        profile.target_role = "software_engineer"
        self.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.engine.dispose()

    def test_roles_and_target_role(self):
        response = self.client.get("/career/roles")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Backend Developer", [x["name"] for x in response.json()])

        response = self.client.put(
            "/career/target-role",
            json={"role_key": "backend_developer"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"]["key"], "backend_developer")

        bad = self.client.put(
            "/career/target-role",
            json={"role_key": "not-a-role"},
        )
        self.assertEqual(bad.status_code, 400)

    def test_progress_resume_mock_and_dashboard(self):
        self.client.put("/career/target-role", json={"role_key": "backend_developer"})
        problem = Problem(
            slug="career-two-sum",
            title="Two Sum",
            difficulty="Easy",
            topics=["Arrays & Strings"],
            description="x",
            constraints=[],
            examples=[],
            test_cases=[],
            starter_code={},
        )
        self.db.add(problem)
        self.db.commit()
        self.db.refresh(problem)
        self.db.add(CodingAttempt(
            user_id=self.user_id,
            problem_id=problem.id,
            language="Python",
            mode="submit",
            code="return",
            status="Accepted",
            summary="ok",
            results=[],
        ))
        self.db.commit()

        response = self.client.put("/career/progress", json={
            "skill_type": "cs_fundamentals",
            "skill_key": "DBMS",
            "status": "completed",
            "score": 90,
            "evidence_count": 3,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["score"], 90)

        resume = self.client.post("/career/resume-analysis", json={
            "role_key": "backend_developer",
            "resume_text": (
                "Python FastAPI Django REST APIs SQL Docker Git DBMS "
                "Operating Systems Computer Networks OOP System Design testing"
            ),
        })
        self.assertEqual(resume.status_code, 200)
        self.assertGreater(resume.json()["alignment_score"], 0)
        self.assertIn("not persisted", resume.json()["privacy"])

        mock = self.client.post("/career/mock-interviews", json={
            "role_key": "backend_developer",
            "mode": "mixed",
            "question_count": 3,
        })
        self.assertEqual(mock.status_code, 200)
        session = mock.json()
        self.assertEqual(session["status"], "in_progress")

        while session["current_question"]:
            question = session["current_question"]
            answer = (
                "I would use a hash map because it gives O(n) expected lookup time. "
                "I would validate inputs, explain the trade-off, test edge cases, "
                "and describe the final result."
            )
            result = self.client.post(
                f"/career/mock-interviews/{session['id']}/responses",
                json={"question_id": question["id"], "answer": answer},
            )
            self.assertEqual(result.status_code, 200)
            next_question = result.json()["next_question"]
            if not next_question:
                break
            session["current_question"] = next_question

        complete = self.client.post(f"/career/mock-interviews/{session['id']}/complete")
        self.assertEqual(complete.status_code, 200)
        self.assertEqual(complete.json()["status"], "completed")
        self.assertIsNotNone(complete.json()["score"])

        dashboard = self.client.get("/career/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        payload = dashboard.json()
        self.assertGreaterEqual(payload["metrics"]["dsa"]["score"], 1)
        self.assertIn("readiness_score", payload)
        self.assertIn("weak_areas", payload)
        self.assertIn("personalized_plan", payload)
        self.assertIn("company_preparation", payload)
        self.assertEqual(payload["profile"]["target_role"], "backend_developer")

    def test_question_bank_filters_and_company_preparation(self):
        behavioral = self.client.get("/career/questions?type=behavioral&limit=100")
        self.assertEqual(behavioral.status_code, 200)
        self.assertTrue(behavioral.json()["questions"])
        self.assertTrue(all(item["type"] == "behavioral" for item in behavioral.json()["questions"]))

        company = self.client.get("/career/questions?company=Google&limit=100")
        self.assertEqual(company.status_code, 200)
        self.assertTrue(company.json()["questions"])

        categories = self.client.get("/career/company-categories")
        self.assertEqual(categories.status_code, 200)
        self.assertIn("Big Tech", categories.json())

    def test_mock_interview_rejects_wrong_current_question(self):
        mock = self.client.post("/career/mock-interviews", json={
            "role_key": "backend_developer",
            "mode": "technical",
            "question_count": 3,
        })
        self.assertEqual(mock.status_code, 200)
        session = mock.json()
        wrong = self.client.post(
            f"/career/mock-interviews/{session['id']}/responses",
            json={"question_id": "behavioral-intro", "answer": "wrong question"},
        )
        self.assertEqual(wrong.status_code, 409)


if __name__ == "__main__":
    unittest.main()
