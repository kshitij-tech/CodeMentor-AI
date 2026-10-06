import unittest

from backend.ai import AIProviderError, _mentor_hint_is_too_solution_like, _mentor_validate_result


class MentorQualityEvaluationTests(unittest.TestCase):
    def test_hint_is_progressive(self):
        result = _mentor_validate_result(
            {
                "answer": "Inspect the invariant and ask what must remain true after each iteration.",
                "error_line": None,
                "patch": None,
            },
            code="left = 0\nright = 1\nwhile left < right:\n    pass",
            language="Python",
            action="hint",
            execution=None,
        )
        self.assertTrue(result["answer"])
        self.assertIsNone(result["patch"])

    def test_hint_gate_rejects_full_solution(self):
        with self.assertRaises(AIProviderError):
            _mentor_validate_result(
                {
                    "answer": "def solve(values):\n    return sorted(values)",
                    "error_line": None,
                    "patch": None,
                },
                code="print(values)",
                language="Python",
                action="hint",
                execution=None,
            )

    def test_debug_uses_execution_evidence(self):
        result = _mentor_validate_result(
            {
                "answer": "Inspect the failing state transition.",
                "error_line": 99,
                "patch": None,
            },
            code="x = 1\nx += unknown",
            language="Python",
            action="debug",
            execution={"status": "Runtime Error", "error_line": 2},
        )
        self.assertEqual(result["error_line"], 2)

    def test_modify_accepts_only_small_local_patch(self):
        result = _mentor_validate_result(
            {
                "answer": "Update the accumulator.",
                "error_line": 2,
                "patch": {
                    "start_line": 2,
                    "end_line": 2,
                    "replacement": "total += value",
                },
            },
            code="total = 0\ntotal = value\nprint(total)",
            language="Python",
            action="modify",
            execution=None,
        )
        self.assertEqual(result["patch"]["start_line"], 2)

    def test_non_modify_drops_patch(self):
        result = _mentor_validate_result(
            {
                "answer": "Inspect the current state.",
                "error_line": None,
                "patch": {"start_line": 1, "end_line": 1, "replacement": "x = 2"},
            },
            code="x = 1",
            language="Python",
            action="complexity",
            execution=None,
        )
        self.assertIsNone(result["patch"])

    def test_solution_gate_is_not_overaggressive(self):
        self.assertFalse(
            _mentor_hint_is_too_solution_like(
                "The word import may refer to your input representation; focus on the state invariant."
            )
        )


if __name__ == "__main__":
    unittest.main()
