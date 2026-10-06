import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import User
from backend.routers.profile import (
    complete_onboarding,
    get_onboarding_status,
    get_profile,
    get_recommendation_context,
    update_profile,
)
from backend.schemas import UserProfileUpsert


class ProfilePreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        self.user_a = User(
            email="a@example.com",
            password_hash="hash-a",
        )
        self.user_b = User(
            email="b@example.com",
            password_hash="hash-b",
        )
        self.db.add_all([self.user_a, self.user_b])
        self.db.commit()
        self.db.refresh(self.user_a)
        self.db.refresh(self.user_b)

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        with Session(self.engine) as cleanup:
            for table in reversed(Base.metadata.sorted_tables):
                cleanup.execute(table.delete())
            cleanup.commit()

    @staticmethod
    def payload(**overrides):
        data = {
            "full_name": "Developer A",
            "preferred_languages": ["Python", "C++"],
            "experience_level": "Intermediate",
            "dsa_familiarity": ["Arrays & Strings", "Hashing & Hash Maps"],
            "target_role": "Backend Engineer",
            "target_companies": ["Google"],
            "target_categories": ["SaaS"],
            "daily_practice_target": 5,
            "learning_preferences": {
                "learning_style": "Hands-on",
                "hint_preference": "Guided",
                "session_length": "30-60 min",
                "feedback_preference": "Balanced",
            },
            "preparation_timeline": "3 Months Deep Dive",
        }
        data.update(overrides)
        return UserProfileUpsert(**data)

    def test_first_profile_is_created_per_user(self):
        profile_a = get_profile(self.user_a, self.db)
        profile_b = get_profile(self.user_b, self.db)

        self.assertEqual(profile_a.user_id, self.user_a.id)
        self.assertEqual(profile_b.user_id, self.user_b.id)
        self.assertEqual(profile_a.id != profile_b.id, True)
        self.assertFalse(profile_a.onboarding_completed)
        self.assertEqual(profile_a.daily_practice_target, 3)

    def test_incomplete_onboarding_is_rejected(self):
        data = self.payload(dsa_familiarity=[], preferred_languages=[])

        with self.assertRaises(HTTPException) as context:
            complete_onboarding(data, self.user_a, self.db)

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("dsa_familiarity", str(context.exception.detail))
        self.assertIn("preferred_languages", str(context.exception.detail))

    def test_completed_onboarding_persists_all_preferences(self):
        data = self.payload()
        profile = complete_onboarding(data, self.user_a, self.db)

        self.assertTrue(profile.onboarding_completed)
        self.assertEqual(profile.preferred_languages, ["Python", "C++"])
        self.assertEqual(profile.preferred_language, "Python")
        self.assertEqual(profile.dsa_familiarity, ["Arrays & Strings", "Hashing & Hash Maps"])
        self.assertEqual(profile.target_categories, ["SaaS"])
        self.assertEqual(profile.daily_practice_target, 5)
        self.assertEqual(profile.learning_preferences["learning_style"], "Hands-on")

    def test_onboarding_cannot_be_completed_twice(self):
        complete_onboarding(self.payload(), self.user_a, self.db)

        with self.assertRaises(HTTPException) as context:
            complete_onboarding(self.payload(), self.user_a, self.db)

        self.assertEqual(context.exception.status_code, 409)

    def test_settings_edit_preserves_completion(self):
        complete_onboarding(self.payload(), self.user_a, self.db)

        updated = update_profile(
            self.payload(
                daily_practice_target=10,
                target_role="Machine Learning Engineer",
                preferred_languages=["Python", "Rust"],
            ),
            self.user_a,
            self.db,
        )

        self.assertTrue(updated.onboarding_completed)
        self.assertEqual(updated.daily_practice_target, 10)
        self.assertEqual(updated.target_role, "Machine Learning Engineer")
        self.assertEqual(updated.preferred_languages, ["Python", "Rust"])

    def test_profiles_are_isolated_between_users(self):
        complete_onboarding(self.payload(full_name="User A"), self.user_a, self.db)
        profile_b = get_profile(self.user_b, self.db)

        self.assertEqual(profile_b.full_name, None)
        self.assertEqual(profile_b.target_role, None)
        self.assertFalse(profile_b.onboarding_completed)

        context_b = get_recommendation_context(self.user_b, self.db)
        self.assertEqual(context_b.experience_level, None)
        self.assertEqual(context_b.preferred_languages, [])
        self.assertEqual(context_b.target_companies, [])

    def test_status_reports_missing_mandatory_fields(self):
        profile = get_profile(self.user_a, self.db)
        self.assertFalse(profile.onboarding_completed)

        status = get_onboarding_status(self.user_a, self.db)
        self.assertFalse(status.onboarding_completed)
        self.assertIn("full_name", status.missing_fields)
        self.assertIn("preferred_languages", status.missing_fields)
        self.assertIn("target", status.missing_fields)

    def test_schema_validates_profile_input(self):
        with self.assertRaises(ValueError):
            self.payload(preferred_languages=["Cobol"])

        with self.assertRaises(ValueError):
            self.payload(preferred_language="Cobol", preferred_languages=[])

        with self.assertRaises(ValueError):
            self.payload(daily_practice_target=0)

        with self.assertRaises(ValueError):
            self.payload(target_role="Astronaut")

        with self.assertRaises(ValueError):
            self.payload(target_categories=["Crypto"])

        with self.assertRaises(ValueError):
            self.payload(
                learning_preferences={
                    "learning_style": "Hands-on",
                    "hint_preference": "Always reveal solution",
                    "session_length": "30-60 min",
                    "feedback_preference": "Balanced",
                }
            )


if __name__ == "__main__":
    unittest.main()
