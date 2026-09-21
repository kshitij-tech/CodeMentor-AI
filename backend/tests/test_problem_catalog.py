import unittest

from backend.problem_catalog import (
    CANONICAL_TOPICS,
    audit_problems,
    canonicalize_topics,
    normalize_difficulty,
    normalize_topic,
    quality_flags,
)


class ProblemCatalogTests(unittest.TestCase):
    def test_difficulty_normalization(self):
        self.assertEqual(normalize_difficulty("easy"), "Easy")
        self.assertEqual(normalize_difficulty("INTERMEDIATE"), "Medium")
        self.assertEqual(normalize_difficulty("Advanced"), "Hard")
        self.assertIsNone(normalize_difficulty("Unknown"))

    def test_topic_normalization(self):
        self.assertEqual(normalize_topic("binary_search"), "Binary Search")
        self.assertEqual(normalize_topic("DP"), "Dynamic Programming")
        self.assertEqual(
            canonicalize_topics(["array", "Arrays & Strings", "binary_search"]),
            ["Arrays & Strings", "Binary Search"],
        )

    def test_quality_flags(self):
        problem = {
            "title": "Two Sum",
            "description": "Given an array of integers and a target, return the indices of the two numbers that add up to the target.",
            "difficulty": "Medium",
            "topics": ["array"],
            "source": "fixture",
            "examples": [{"input": "[2,7,11,15], 9", "output": "[0,1]"}],
            "test_cases": [{"input": "2 7 9", "expected_output": "0 1"}],
            "starter_code": {"Python": "def solve():\n    pass\n"},
        }
        self.assertEqual(quality_flags(problem), [])

    def test_quality_detects_missing_tests_and_starter(self):
        problem = {
            "title": "Two Sum",
            "description": "Given an array of integers and a target, return the indices of the two numbers that add up to the target.",
            "difficulty": "Medium",
            "topics": ["array"],
            "source": "fixture",
            "examples": [{"input": "x", "output": "y"}],
            "test_cases": [],
            "starter_code": {},
        }
        flags = quality_flags(problem)
        self.assertIn("missing_or_invalid_tests", flags)
        self.assertIn("missing_starter_code", flags)

    def test_duplicate_audit(self):
        base = {
            "title": "Two Sum",
            "description": "Given an array of integers and a target, return the indices of the two numbers that add up to the target.",
            "difficulty": "Medium",
            "topics": ["array"],
            "source": "fixture",
            "examples": [{"input": "x", "output": "y"}],
            "test_cases": [{"input": "x", "expected_output": "y"}],
            "starter_code": {"Python": "def solve():\n    pass\n"},
        }
        first = {**base, "slug": "two-sum-a", "external_id": None}
        second = {**base, "slug": "two-sum-b", "external_id": None}
        report = audit_problems([first, second])
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["clean"], 2)
        self.assertEqual(len(report["duplicates"]["same_content"]), 1)

    def test_canonical_topic_catalog_is_stable(self):
        self.assertIn("Binary Search", CANONICAL_TOPICS)
        self.assertIn("Dynamic Programming", CANONICAL_TOPICS)


if __name__ == "__main__":
    unittest.main()
