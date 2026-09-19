import unittest

from backend.validator import UnsupportedValidatorError, validate_default_output


class DefaultValidatorTests(unittest.TestCase):
    def test_default_is_whitespace_and_case_insensitive(self):
        result = validate_default_output("Hello\tWORLD\n", "hello world\n")
        self.assertTrue(result.passed)

    def test_case_sensitive_rejects_case_difference(self):
        result = validate_default_output(
            "Hello",
            "hello",
            ["case_sensitive"],
        )
        self.assertFalse(result.passed)

    def test_space_sensitive_rejects_whitespace_difference(self):
        result = validate_default_output(
            "1  2",
            "1 2",
            ["space_change_sensitive"],
        )
        self.assertFalse(result.passed)

    def test_float_tolerance_accepts_close_value(self):
        result = validate_default_output(
            "3.1415927",
            "3.1415926",
            ["float_tolerance", "0.000001"],
        )
        self.assertTrue(result.passed)

    def test_float_tolerance_rejects_far_value(self):
        result = validate_default_output(
            "3.15",
            "3.14",
            ["float_tolerance", "0.000001"],
        )
        self.assertFalse(result.passed)

    def test_duplicate_float_modes_are_rejected(self):
        with self.assertRaises(UnsupportedValidatorError):
            validate_default_output(
                "1.0",
                "1.0",
                ["float_tolerance", "0.1", "float_relative_tolerance", "0.1"],
            )


if __name__ == "__main__":
    unittest.main()
