import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from roadmap.adaptive_learning import (
    MASTERED_CONFIDENCE,
    MASTERED_MASTERY,
    PREREQUISITE_CONFIDENCE,
    PREREQUISITE_MASTERY,
    adaptive_difficulty,
    build_learning_state,
    build_roadmap,
    explain_recommendation,
    mastered_topics,
    recommend_problem,
    skills_payload,
    weak_topics,
)


NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def problem(
    problem_id,
    title,
    difficulty,
    topics,
):
    return {
        "id": problem_id,
        "slug": title.lower().replace(" ", "-"),
        "title": title,
        "difficulty": difficulty,
        "topics": topics,
    }


def attempt(
    attempt_id,
    problem_id,
    *,
    status="Accepted",
    mode="submit",
    days_ago=0,
):
    return SimpleNamespace(
        id=attempt_id,
        problem_id=problem_id,
        status=status,
        mode=mode,
        created_at=NOW - timedelta(days=days_ago),
    )


class AdaptiveLearningTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            problem(1, "Arrays Easy 1", "Easy", ["Arrays & Strings"]),
            problem(2, "Arrays Easy 2", "Easy", ["Arrays & Strings"]),
            problem(3, "Arrays Easy 3", "Easy", ["Arrays & Strings"]),
            problem(4, "Arrays Easy 4", "Easy", ["Arrays & Strings"]),
            problem(5, "Sorting Medium 1", "Medium", ["Sorting"]),
            problem(6, "Sorting Medium 2", "Medium", ["Sorting"]),
            problem(7, "Sorting Medium 3", "Medium", ["Sorting"]),
            problem(8, "Sorting Medium 4", "Medium", ["Sorting"]),
            problem(9, "Sliding Window", "Medium", ["Sliding Window"]),
            problem(10, "Arrays Hard", "Hard", ["Arrays & Strings"]),
        ]

    def test_skill_score_uses_accepted_and_failed_weighting(self):
        accepted = build_learning_state(
            self.catalog,
            [attempt(1, 1, status="Accepted")],
            now=NOW,
        )
        wrong = build_learning_state(
            self.catalog,
            [attempt(1, 1, status="Wrong Answer")],
            now=NOW,
        )
        self.assertGreater(
            accepted.topics["Arrays & Strings"].skill_score,
            wrong.topics["Arrays & Strings"].skill_score,
        )

    def test_recency_makes_recent_outcome_more_influential(self):
        recent_success = build_learning_state(
            self.catalog,
            [
                attempt(1, 1, status="Wrong Answer", days_ago=60),
                attempt(2, 1, status="Accepted", days_ago=0),
            ],
            now=NOW,
        )
        recent_failure = build_learning_state(
            self.catalog,
            [
                attempt(1, 1, status="Accepted", days_ago=60),
                attempt(2, 1, status="Wrong Answer", days_ago=0),
            ],
            now=NOW,
        )
        self.assertGreater(
            recent_success.topics["Arrays & Strings"].skill_score,
            recent_failure.topics["Arrays & Strings"].skill_score,
        )

    def test_confidence_requires_distinct_evidence(self):
        one_problem = build_learning_state(
            self.catalog,
            [attempt(1, 1), attempt(2, 1), attempt(3, 1)],
            now=NOW,
        )
        three_problems = build_learning_state(
            self.catalog,
            [attempt(1, 1), attempt(2, 2), attempt(3, 3)],
            now=NOW,
        )
        self.assertLess(
            one_problem.topics["Arrays & Strings"].confidence,
            three_problems.topics["Arrays & Strings"].confidence,
        )
        self.assertLess(
            one_problem.topics["Arrays & Strings"].mastery,
            100,
        )

    def test_run_attempt_is_history_but_does_not_mark_problem_solved(self):
        state = build_learning_state(
            self.catalog,
            [attempt(1, 1, mode="run", status="Accepted")],
            now=NOW,
        )
        self.assertNotIn(1, state.solved_ids)
        self.assertIn(1, state.attempted_ids)
        self.assertEqual(state.topics["Arrays & Strings"].submissions, 0)

    def test_mastery_threshold_identifies_mastered_topic(self):
        state = build_learning_state(
            self.catalog,
            [
                attempt(1, 1),
                attempt(2, 2),
                attempt(3, 3),
                attempt(4, 4),
            ],
            now=NOW,
        )
        metric = state.topics["Arrays & Strings"]
        self.assertGreaterEqual(metric.mastery, MASTERED_MASTERY)
        self.assertGreaterEqual(metric.confidence, MASTERED_CONFIDENCE)
        self.assertIn("Arrays & Strings", [m.key for m in mastered_topics(state)])

    def test_medium_progression_unlocks_after_strong_easy_evidence(self):
        attempts = [
            attempt(1, 1),
            attempt(2, 2),
            attempt(3, 3),
            attempt(4, 4),
        ]
        state = build_learning_state(self.catalog, attempts, now=NOW)
        policy = adaptive_difficulty(state, experience_level="Beginner")
        self.assertTrue(policy["medium_ready"])
        self.assertEqual(policy["target"], "Medium")

    def test_hard_is_not_recommended_before_medium_mastery(self):
        state = build_learning_state(
            self.catalog,
            [
                attempt(1, 1),
                attempt(2, 2),
                attempt(3, 3),
                attempt(4, 4),
            ],
            now=NOW,
        )
        selected, breakdown = recommend_problem(
            self.catalog,
            state,
            experience_level="Beginner",
        )
        self.assertIsNotNone(selected)
        self.assertNotEqual(selected["difficulty"], "Hard")
        self.assertFalse(breakdown["difficulty_policy"]["hard_ready"])

    def test_hard_unlocks_only_after_four_strong_medium_problems(self):
        attempts = [
            attempt(1, 1),
            attempt(2, 2),
            attempt(3, 3),
            attempt(4, 4),
            attempt(5, 5),
            attempt(6, 6),
            attempt(7, 7),
            attempt(8, 8),
        ]
        state = build_learning_state(self.catalog, attempts, now=NOW)
        policy = adaptive_difficulty(state, experience_level="Advanced")
        self.assertTrue(policy["hard_ready"])
        self.assertEqual(policy["target"], "Hard")

    def test_recent_mistake_increases_topic_reinforcement_signal(self):
        catalog = [
            problem(1, "Array Practice", "Easy", ["Arrays & Strings"]),
        ]
        state = build_learning_state(
            catalog,
            [attempt(1, 1, status="Wrong Answer")],
            now=NOW,
        )
        selected, breakdown = recommend_problem(
            catalog,
            state,
            experience_level="Beginner",
        )
        self.assertEqual(selected["id"], 1)
        self.assertGreater(breakdown["recent_mistake_signal"], 0)
        self.assertTrue(
            "recent failed submissions" in explain_recommendation(
                catalog[0],
                state,
                experience_level="Beginner",
            )["why"]
        )

    def test_solved_history_is_excluded_and_same_state_is_deterministic(self):
        attempts = [attempt(1, 1)]
        state = build_learning_state(self.catalog, attempts, now=NOW)
        first, first_details = recommend_problem(
            self.catalog,
            state,
            experience_level="Beginner",
        )
        second, second_details = recommend_problem(
            self.catalog,
            state,
            experience_level="Beginner",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first_details["score"], second_details["score"])
        self.assertNotEqual(first["id"], 1)

    def test_prerequisite_graph_locks_dependent_topic(self):
        state = build_learning_state(self.catalog, [], now=NOW)
        roadmap = build_roadmap(
            self.catalog,
            state,
            experience_level="Beginner",
        )
        rows = {row["topic"]: row for row in roadmap["items"]}
        # Sorting is not selected as current until Arrays evidence unlocks it.
        self.assertIn("Sorting", rows)
        self.assertFalse(rows["Sorting"]["unlocked"])
        self.assertIn("Arrays & Strings", rows["Sorting"]["unmet_prerequisites"])

    def test_prerequisite_unlocks_after_mastery(self):
        state = build_learning_state(
            self.catalog,
            [
                attempt(1, 1),
                attempt(2, 2),
                attempt(3, 3),
                attempt(4, 4),
            ],
            now=NOW,
        )
        roadmap = build_roadmap(
            self.catalog,
            state,
            experience_level="Beginner",
        )
        rows = {row["topic"]: row for row in roadmap["items"]}
        self.assertTrue(
            state.topics["Arrays & Strings"].mastery >= PREREQUISITE_MASTERY
        )
        self.assertTrue(
            state.topics["Arrays & Strings"].confidence >= PREREQUISITE_CONFIDENCE
        )
        self.assertTrue(rows["Sorting"]["unlocked"])

    def test_skills_payload_contains_topic_difficulty_and_visualization_data(self):
        state = build_learning_state(
            self.catalog,
            [attempt(1, 1)],
            now=NOW,
        )
        payload = skills_payload(state, experience_level="Beginner")
        self.assertEqual(
            [item["key"] for item in payload["difficulties"]],
            ["Easy", "Medium", "Hard"],
        )
        self.assertEqual(
            len(payload["visualization"]["labels"]),
            len(payload["topics"]),
        )
        self.assertIn("Arrays & Strings", payload["weak_topics"])

    def test_why_explanation_uses_recommendation_factors(self):
        state = build_learning_state(
            self.catalog,
            [attempt(1, 1, status="Wrong Answer")],
            now=NOW,
        )
        explanation = explain_recommendation(
            self.catalog[1],
            state,
            experience_level="Beginner",
            candidate_count=len(self.catalog),
        )
        breakdown = explanation["score_breakdown"]
        self.assertIn("skill_gap", breakdown)
        self.assertIn("prerequisites_met", breakdown)
        self.assertIn("difficulty_target", breakdown)
        self.assertIn("recent_mistake_signal", breakdown)
        self.assertIn("repetition_penalty", breakdown)
        self.assertTrue(explanation["why"].startswith("Recommended because"))

    def test_weak_topics_prioritize_evidenced_gaps_over_untouched_topics(self):
        catalog = [
            problem(1, "Arrays Practice", "Easy", ["Arrays & Strings"]),
            problem(2, "Sorting Practice", "Easy", ["Sorting"]),
        ]
        state = build_learning_state(
            catalog,
            [attempt(1, 1, status="Wrong Answer")],
            now=NOW,
        )
        weak = weak_topics(state, limit=2)
        self.assertEqual(weak[0].key, "Arrays & Strings")


if __name__ == "__main__":
    unittest.main()
