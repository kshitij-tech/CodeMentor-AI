import subprocess
import sys
import unittest

from backend.stdio_adapter import (
    adapt_stdio_source,
    editor_schema_from_metadata,
    generate_stdio_editor_starters,
)


class StdioAdapterTests(unittest.TestCase):
    def test_explicit_schema_generates_function_starters_for_all_languages(self):
        schema = [
            {"name": "n", "type": "int"},
            {"name": "nums", "type": "int_array", "length_from": "n"},
        ]
        starters = generate_stdio_editor_starters(schema)

        self.assertIn("solve(n, nums)", starters["Python"])
        self.assertIn("solve(", starters["C++"])
        self.assertIn("nums", starters["C++"])
        self.assertIn("solve(", starters["Java"])
        self.assertIn("nums", starters["Java"])
        self.assertIn("solve(n, nums)", starters["JavaScript"])
        self.assertIn("solve(n: number, nums: any)", starters["TypeScript"])
        self.assertIn("solve(n int64", starters["Go"])
        self.assertIn("nums: Vec<i64>", starters["Rust"])

    def test_stdio_schema_can_be_inferred_from_statement_and_sample(self):
        description = (
            "Input:\n"
            "The first line contains an integer n.\n"
            "The second line contains an array nums of n integers.\n"
            "Output:\nPrint the answer."
        )
        examples = [{"input": "3\n1 2 3\n", "output": "6\n"}]
        schema = editor_schema_from_metadata({}, description, examples)

        self.assertEqual(schema[0]["name"], "n")
        self.assertEqual(schema[0]["type"], "int")
        self.assertEqual(schema[1]["name"], "nums")
        self.assertEqual(schema[1]["type"], "int_array")
        self.assertEqual(schema[1]["length_from"], "n")

    def test_unsafe_inferred_schema_falls_back_to_raw_input(self):
        description = (
            "Input:\n"
            "The array nums contains values and a target value is provided.\n"
            "Output:\nPrint the answer."
        )
        examples = [{"input": "3 1 2 3 7\n", "output": "3\n"}]
        schema = editor_schema_from_metadata({}, description, examples)

        self.assertEqual(schema, [{"name": "input_data", "type": "raw_string"}])

    def test_python_adapter_passes_parsed_arguments_to_solve(self):
        source = """def solve(n, nums):
    return n + sum(nums)
"""
        adapted = adapt_stdio_source(
            source,
            "Python",
            [
                {"name": "n", "type": "int"},
                {"name": "nums", "type": "int_array", "length_from": "n"},
            ],
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", adapted],
            input="3\n1 2 3\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "9\n")

    def test_python_raw_input_fallback_preserves_entire_stdin(self):
        source = """def solve(input_data):
    return input_data.strip().upper()
"""
        adapted = adapt_stdio_source(
            source,
            "Python",
            [{"name": "input_data", "type": "raw_string"}],
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", adapted],
            input="hello world\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "HELLO WORLD\n")

    def test_generated_adapters_have_program_entrypoint(self):
        schema = [{"name": "n", "type": "int"}]
        sources = {
            "C++": "int solve(long long n) { return static_cast<int>(n); }",
            "Java": "class Solution { public Object solve(long n) { return n; } }",
            "JavaScript": "function solve(n) { return n; }",
            "TypeScript": "function solve(n: number): any { return n; }",
            "Go": "package main\n\nfunc solve(n int64) any { return n }",
            "Rust": "fn solve(n: i64) -> String { n.to_string() }",
        }

        for language, source in sources.items():
            with self.subTest(language=language):
                adapted = adapt_stdio_source(source, language, schema)
                self.assertRegex(adapted, r"\\bmain\\s*\\(")
                self.assertIn("solve(", adapted)

    def test_go_user_imports_are_preserved(self):
        source = '''package main

import "sort"

func solve(n int64) any {
    values := []int{3, 1, 2}
    sort.Ints(values)
    return values[0] + int(n)
}
'''
        adapted = adapt_stdio_source(
            source,
            "Go",
            [{"name": "n", "type": "int"}],
        )
        self.assertIn('"sort"', adapted)
        self.assertIn('"bufio"', adapted)
        self.assertIn("sort.Ints(values)", adapted)


if __name__ == "__main__":
    unittest.main()
