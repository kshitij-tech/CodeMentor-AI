import unittest

from backend.import_problems import validate


class ImportProblemValidationTests(unittest.TestCase):
    BASE = {
        "slug": "two-sum",
        "title": "Two Sum",
        "difficulty": "Easy",
        "topics": ["array", "hash map"],
        "description": "Given an array of integers and a target, return the indices of two values that sum to the target.",
        "constraints": ["2 <= n <= 100000"],
        "examples": [{"input": "nums = [2,7], target = 9", "output": "[0,1]"}],
        "test_cases": [{"args": [[2, 7], 9], "expected": [0, 1]}],
        "starter_code": {
            "Python": "def solve(nums, target):
    return [0, 1]
",
            "C++": "int solve(vector<int> nums, int target) { return 0; }
",
            "Java": "class Solution { int solve(int[] nums, int target) { return 0; } }
",
            "JavaScript": "function solve(nums, target) { return [0, 1]; }
",
            "TypeScript": "function solve(nums: any[], target: number): any[] { return [0, 1]; }
",
            "Go": "package main
func solve(nums []int, target int) []int { return []int{0,1} }
",
            "Rust": "fn solve(nums: &[i32], target: i32) -> Vec<i32> { vec![0,1] }
",
        },
        "execution_mode": "function",
    }

    def test_validates_and_normalizes_legacy_topics(self):
        problem = validate(dict(self.BASE), 1)
        self.assertEqual(problem["topics"], ["Arrays", "Hashing"])
        self.assertIn("supported_languages", problem["package_metadata"])

    def test_rejects_missing_test_cases(self):
        problem = dict(self.BASE)
        problem.pop("test_cases")
        with self.assertRaisesRegex(ValueError, "missing"):
            validate(problem, 1)

    def test_rejects_malformed_examples(self):
        problem = {**self.BASE, "examples": [{"input": "nums = [2,7]"}]}
        with self.assertRaisesRegex(ValueError, "broken_examples"):
            validate(problem, 1)

    def test_rejects_unknown_difficulty(self):
        problem = {**self.BASE, "difficulty": "Unknown"}
        with self.assertRaisesRegex(ValueError, "unknown_difficulty"):
            validate(problem, 1)

    def test_rejects_invalid_topic_name(self):
        problem = {**self.BASE, "topics": ["arrays", "not-a-topic"]}
        with self.assertRaisesRegex(ValueError, "invalid topic names"):
            validate(problem, 1)

    def test_rejects_broken_starter_code(self):
        problem = {**self.BASE, "starter_code": dict(self.BASE["starter_code"])}
        problem["starter_code"]["Python"] = "def solve(nums, target)\n    return []\n"
        with self.assertRaisesRegex(ValueError, "broken_starter_code"):
            validate(problem, 1)


if __name__ == "__main__":
    unittest.main()
