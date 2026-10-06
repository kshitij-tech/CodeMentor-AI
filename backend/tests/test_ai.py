import unittest

from backend.ai import (
    AIProviderError,
    _extract_message_text,
    _normalize_model,
    _normalize_provider,
    _parse_mentor_response,
    _strip_visible_thinking,
)


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




class AIProviderConfigurationTests(unittest.TestCase):
    def test_ollama_is_the_default_provider(self):
        self.assertEqual(_normalize_provider("ollama"), "ollama")
        self.assertEqual(_normalize_provider("local"), "ollama")

    def test_lmstudio_provider_is_supported(self):
        self.assertEqual(_normalize_provider("lmstudio"), "lmstudio")
        self.assertEqual(
            _normalize_model("", "lmstudio"),
            "mistralai/ministral-3-3b",
        )

    def test_mistral_provider_is_still_supported(self):
        self.assertEqual(_normalize_provider("mistral"), "mistral")
        self.assertEqual(_normalize_model("mistral-small-latest", "mistral"), "mistral-small-latest")

    def test_ollama_default_model(self):
        self.assertEqual(_normalize_model("", "ollama"), "qwen3:4b")

    def test_invalid_provider_is_rejected(self):
        with self.assertRaises(AIProviderError):
            _normalize_provider("gemini")

    def test_extracts_ollama_message_content(self):
        result = _extract_message_text(
            {"message": {"role": "assistant", "content": '{"answer":"ok","error_line":null,"patch":null}'}},
            "ollama",
        )
        self.assertIn('"answer":"ok"', result)

    def test_strips_visible_thinking_block(self):
        result = _strip_visible_thinking(
            "<think>internal reasoning that must not be shown</think>"
            '{"answer":"ok","error_line":null,"patch":null}'
        )
        self.assertEqual(result, '{"answer":"ok","error_line":null,"patch":null}')

    def test_ollama_thinking_field_is_not_exposed(self):
        result = _extract_message_text(
            {
                "message": {
                    "role": "assistant",
                    "thinking": "long internal reasoning",
                    "content": '{"answer":"ok","error_line":null,"patch":null}',
                }
            },
            "ollama",
        )
        self.assertEqual(result, '{"answer":"ok","error_line":null,"patch":null}')

if __name__ == "__main__":
    unittest.main()