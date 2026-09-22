import unittest

from backend.problem_catalog import (
    CANONICAL_TOPICS,
    audit_problems,
    canonicalize_topics,
    normalize_difficulty,
    normalize_topic,
    quality_flags,
    strip_examples_from_description,
    ensure_starter_code,
    SUPPORTED_LANGUAGES,
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


    def test_strip_duplicated_examples(self):
        description = (
            "Given an array of integers, return the indices of two values that add up to target. "
            "Examples: Example 1: Input: nums = [2,7], target = 9 Output: [0,1]"
        )
        cleaned = strip_examples_from_description(
            description,
            [{"input": "nums = [2,7], target = 9", "output": "[0,1]"}],
        )
        self.assertEqual(
            cleaned,
            "Given an array of integers, return the indices of two values that add up to target.",
        )

    def test_strip_embedded_examples_without_structured_examples(self):
        description = (
            "You are given an equation with question marks. Determine whether "
            "the question marks can be replaced to reach the target. "
            "Examples Input ? + ? - ? + ? + ? = 42 Output Possible "
            "9 + 13 - 39 + 28 + 31 = 42 Input ? - ? = 1 Output Impossible "
            "Input ? = 1000000 Output Possible 1000000 = 1000000"
        )
        cleaned = strip_examples_from_description(description, [])
        self.assertEqual(
            cleaned,
            "You are given an equation with question marks. Determine whether "
            "the question marks can be replaced to reach the target.",
        )
    def test_all_supported_languages_receive_starters_for_stdio(self):
        starters = ensure_starter_code({"Python": "def solve():\n    pass\n"}, "stdio")
        self.assertEqual(set(starters), set(SUPPORTED_LANGUAGES))
        self.assertIn("int main()", starters["C++"])
        self.assertIn("public class Main", starters["Java"])
        self.assertIn("process.stdout.write", starters["JavaScript"])
        self.assertIn("func main()", starters["Go"])
        self.assertIn("fn main()", starters["Rust"])

    def test_existing_starters_are_not_overwritten(self):
        original = "class Solution {\n    public int solve(int[] nums) { return 1; }\n}"
        starters = ensure_starter_code({"Java": original}, "function")
        self.assertEqual(starters["Java"], original)

    def test_function_starters_exist_for_all_languages(self):
        starters = ensure_starter_code({}, "function")
        self.assertIn("class Solution", starters["Java"])
        self.assertIn("function solve", starters["JavaScript"])
        self.assertIn("func solve", starters["Go"])
        self.assertIn("fn solve", starters["Rust"])

    def test_function_starters_use_named_problem_parameters(self):
        starters = ensure_starter_code(
            {
                "Python": "def solve(nums, budget):\n    pass\n",
            },
            "function",
            [{"args": [[[2, 1, 3], 6]], "expected": 2}],
        )
        self.assertIn("solve(nums, budget)", starters["Python"])
        self.assertIn("solve(nums, budget)", starters["JavaScript"])
        self.assertIn("solve(nums: any, budget: any)", starters["TypeScript"])
        self.assertIn("solve(nums", starters["C++"])
        self.assertIn("budget", starters["Java"])
        self.assertIn("budget", starters["Go"])
        self.assertIn("budget", starters["Rust"])

    def test_generic_function_boilerplate_is_replaced_from_examples(self):
        starters = ensure_starter_code(
            {"Python": "def solve(*args):\n    pass\n"},
            "function",
            [{"args": [[4, 7, 2, 7, 9]], "expected": 7}],
            [{"input": "nums = [4, 7, 2, 7, 9]", "output": "7"}],
        )
        self.assertIn("def solve(nums):", starters["Python"])
        self.assertIn("function solve(nums)", starters["JavaScript"])
        self.assertNotIn("*args", starters["Python"])
        self.assertNotIn("...args", starters["JavaScript"])

    def test_canonical_topic_catalog_is_stable(self):
        self.assertIn("Binary Search", CANONICAL_TOPICS)
        self.assertIn("Dynamic Programming", CANONICAL_TOPICS)


if __name__ == "__main__":
    unittest.main()
