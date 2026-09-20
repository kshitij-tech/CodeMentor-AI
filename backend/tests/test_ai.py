import unittest

from backend.ai import _parse_mentor_response


class MentorResponseParsingTests(unittest.TestCase):
    def test_parses_normal_json(self):
        result = _parse_mentor_response(
            '{"answer":"Check the loop condition.","error_line":4,"patch":null}'
        )
        self.assertEqual(result["answer"], "Check the loop condition.")
        self.assertEqual(result["error_line"], 4)
        self.assertIsNone(result["patch"])

    def test_parses_fenced_json(self):
        result = _parse_mentor_response(
            '```json\n{"answer":"Try a two-pointer approach.","error_line":null,"patch":null}\n```'
        )
        self.assertEqual(result["answer"], "Try a two-pointer approach.")
        self.assertIsNone(result["error_line"])

    def test_ignores_prose_around_json(self):
        result = _parse_mentor_response(
            'Here is the result:\n{"answer":"Handle the empty input.","error_line":null,"patch":null}\nDone.'
        )
        self.assertEqual(result["answer"], "Handle the empty input.")


if __name__ == "__main__":
    unittest.main()