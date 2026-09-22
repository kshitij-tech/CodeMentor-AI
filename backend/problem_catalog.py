from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Any, Iterable

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}

SUPPORTED_LANGUAGES = (
    "Python",
    "C++",
    "Java",
    "JavaScript",
    "TypeScript",
    "Go",
    "Rust",
)

FUNCTION_STARTERS = {
    "Python": (
        "def solve(*args):\\n"
        "    # Implement the required solution.\\n"
        "    pass\\n"
    ),
    "C++": (
        "#include <bits/stdc++.h>\\n"
        "using namespace std;\\n\\n"
        "int solve() {\\n"
        "    // Implement the required solution.\\n"
        "    return 0;\\n"
        "}\\n"
    ),
    "Java": (
        "class Solution {\\n"
        "    public int solve() {\\n"
        "        // Implement the required solution.\\n"
        "        return 0;\\n"
        "    }\\n"
        "}\\n"
    ),
    "JavaScript": (
        "function solve(...args) {\\n"
        "    // Implement the required solution.\\n"
        "    return null;\\n"
        "}\\n"
    ),
    "TypeScript": (
        "function solve(...args: any[]): any {\\n"
        "    // Implement the required solution.\\n"
        "    return null;\\n"
        "}\\n"
    ),
    "Go": (
        "package main\\n\\n"
        "func solve(args ...interface{}) interface{} {\\n"
        "    // Implement the required solution.\\n"
        "    return nil\\n"
        "}\\n"
    ),
    "Rust": (
        "fn solve(args: &[String]) -> String {\\n"
        "    // Implement the required solution.\\n"
        "    String::new()\\n"
        "}\\n"
    ),
}


def _function_parameter_names(starter: Any) -> list[str]:
    """Extract named parameters from an existing Python solve() starter."""
    if not isinstance(starter, str) or not starter.strip():
        return []
    try:
        tree = __import__("ast").parse(starter)
    except (SyntaxError, TypeError, ValueError):
        return []
    for node in __import__("ast").walk(tree):
        if isinstance(node, __import__("ast").FunctionDef) and node.name == "solve":
            names = [arg.arg for arg in node.args.posonlyargs]
            names.extend(arg.arg for arg in node.args.args)
            names.extend(arg.arg for arg in node.args.kwonlyargs)
            return [name for name in names if name]
    return []


def _argument_values(test_cases: Any, count: int) -> list[Any]:
    if not isinstance(test_cases, list):
        return [None] * count
    for case in test_cases:
        if not isinstance(case, dict) or "args" not in case:
            continue
        args = case.get("args")
        if not isinstance(args, list):
            continue
        return list(args[:count]) + [None] * max(0, count - len(args))
    return [None] * count


def _inferred_cpp_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "long long"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        inner = _inferred_cpp_type(value[0]) if value else "long long"
        return f"vector<{inner}>"
    return "auto"


def _inferred_java_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "long"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "String"
    if isinstance(value, list):
        inner = _inferred_java_type(value[0]) if value else "long"
        return f"{inner}[]"
    return "Object"


def _inferred_go_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float64"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        inner = _inferred_go_type(value[0]) if value else "int"
        return f"[]{inner}"
    return "any"


def _inferred_rust_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "i64"
    if isinstance(value, float):
        return "f64"
    if isinstance(value, str):
        return "&str"
    if isinstance(value, list):
        inner = _inferred_rust_type(value[0]) if value else "i64"
        return f"&[{inner}]"
    return "&dyn std::any::Any"


def _generated_function_starters(
    names: list[str],
    values: list[Any],
) -> dict[str, str]:
    if not names:
        return {language: FUNCTION_STARTERS[language] for language in SUPPORTED_LANGUAGES}

    cpp_params = ", ".join(
        f"{_inferred_cpp_type(value)}& {name}" if isinstance(value, list)
        else f"{_inferred_cpp_type(value)} {name}"
        for name, value in zip(names, values)
    )
    java_params = ", ".join(
        f"{_inferred_java_type(value)} {name}"
        for name, value in zip(names, values)
    )
    js_params = ", ".join(names)
    go_params = ", ".join(
        f"{name} {_inferred_go_type(value)}"
        for name, value in zip(names, values)
    )
    rust_params = ", ".join(
        f"{name}: {_inferred_rust_type(value)}"
        for name, value in zip(names, values)
    )

    return {
        "Python": f"def solve({', '.join(names)}):\\n    # Implement the required solution.\\n    pass\\n",
        "C++": f"#include <bits/stdc++.h>\\nusing namespace std;\\n\\nlong long solve({cpp_params}) {{\\n    // Implement the required solution.\\n    return 0;\\n}}\\n",
        "Java": f"class Solution {{\\n    public long solve({java_params}) {{\\n        // Implement the required solution.\\n        return 0;\\n    }}\\n}}\\n",
        "JavaScript": f"function solve({js_params}) {{\\n    // Implement the required solution.\\n    return null;\\n}}\\n",
        "TypeScript": f"function solve({', '.join(f'{name}: any' for name in names)}): any {{\\n    // Implement the required solution.\\n    return null;\\n}}\\n",
        "Go": f"package main\\n\\nfunc solve({go_params}) int {{\\n    // Implement the required solution.\\n    return 0\\n}}\\n",
        "Rust": f"fn solve({rust_params}) -> i64 {{\\n    // Implement the required solution.\\n    0\\n}}\\n",
    }

STDIO_STARTERS = {
    "Python": (
        "import sys\n\n"
        "def solve():\n"
        "    # Read from standard input and write the required answer.\n"
        "    pass\n\n"
        "if __name__ == '__main__':\n"
        "    solve()\n"
    ),
    "C++": (
        "#include <bits/stdc++.h>\n"
        "using namespace std;\n\n"
        "int main() {\n"
        "    // Read from standard input and write the required answer.\n"
        "    return 0;\n"
        "}\n"
    ),
    "Java": (
        "import java.io.*;\n"
        "import java.util.*;\n\n"
        "public class Main {\n"
        "    public static void main(String[] args) throws Exception {\n"
        "        // Read from standard input and write the required answer.\n"
        "    }\n"
        "}\n"
    ),
    "JavaScript": (
        "const fs = require('fs');\n"
        "const input = fs.readFileSync(0, 'utf8').trim();\n\n"
        "function solve(input) {\n"
        "    // Read input and return the required answer.\n"
        "    return '';\n"
        "}\n\n"
        "process.stdout.write(String(solve(input)));\n"
    ),
    "TypeScript": (
        "declare const require: (name: string) => any;\n"
        "const fs: any = require('fs');\n"
        "const input = fs.readFileSync(0, 'utf8').trim();\n\n"
        "function solve(input: string): string {\n"
        "    // Read input and return the required answer.\n"
        "    return '';\n"
        "}\n\n"
        "process.stdout.write(String(solve(input)));\n"
    ),
    "Go": (
        "package main\n\n"
        "import (\n"
        "    \"bufio\"\n"
        "    \"fmt\"\n"
        "    \"os\"\n"
        ")\n\n"
        "func main() {\n"
        "    in := bufio.NewReader(os.Stdin)\n"
        "    _ = in\n"
        "    // Read from standard input and write the required answer.\n"
        "    fmt.Print()\n"
        "}\n"
    ),
    "Rust": (
        "use std::io::{self, Read};\n\n"
        "fn main() {\n"
        "    let mut input = String::new();\n"
        "    io::stdin().read_to_string(&mut input).unwrap();\n"
        "    // Read input and write the required answer.\n"
        "    print!(\"{}\", input);\n"
        "}\n"
    ),
}

CANONICAL_TOPICS = (
    "Arrays & Strings",
    "Hashing & Hash Maps",
    "Two Pointers",
    "Sliding Window",
    "Binary Search",
    "Linked Lists",
    "Stacks & Queues",
    "Trees & BST",
    "Heaps & Priority Queues",
    "Graphs (BFS/DFS)",
    "Backtracking",
    "Greedy Algorithms",
    "Dynamic Programming",
    "Bit Manipulation",
    "Intervals",
    "Prefix Sum",
    "Sorting",
    "Math",
)

_TOPIC_ALIASES = {
    "arrays strings": "Arrays & Strings",
    "array": "Arrays & Strings",
    "arrays": "Arrays & Strings",
    "string": "Arrays & Strings",
    "strings": "Arrays & Strings",
    "hashing": "Hashing & Hash Maps",
    "hash table": "Hashing & Hash Maps",
    "hash tables": "Hashing & Hash Maps",
    "hash map": "Hashing & Hash Maps",
    "hash maps": "Hashing & Hash Maps",
    "map": "Hashing & Hash Maps",
    "maps": "Hashing & Hash Maps",
    "unordered map": "Hashing & Hash Maps",
    "data structures": "Hashing & Hash Maps",
    "two pointer": "Two Pointers",
    "two pointers": "Two Pointers",
    "two-pointer": "Two Pointers",
    "two-pointers": "Two Pointers",
    "sliding window": "Sliding Window",
    "sliding-window": "Sliding Window",
    "binary search": "Binary Search",
    "binary_search": "Binary Search",
    "linked list": "Linked Lists",
    "linked lists": "Linked Lists",
    "linked-list": "Linked Lists",
    "linked-lists": "Linked Lists",
    "stack": "Stacks & Queues",
    "stacks": "Stacks & Queues",
    "queue": "Stacks & Queues",
    "queues": "Stacks & Queues",
    "stacks queues": "Stacks & Queues",
    "tree": "Trees & BST",
    "trees": "Trees & BST",
    "binary search tree": "Trees & BST",
    "bst": "Trees & BST",
    "heap": "Heaps & Priority Queues",
    "heaps": "Heaps & Priority Queues",
    "priority queue": "Heaps & Priority Queues",
    "priority queues": "Heaps & Priority Queues",
    "graph": "Graphs (BFS/DFS)",
    "graphs": "Graphs (BFS/DFS)",
    "bfs": "Graphs (BFS/DFS)",
    "dfs": "Graphs (BFS/DFS)",
    "shortest path": "Graphs (BFS/DFS)",
    "shortest paths": "Graphs (BFS/DFS)",
    "backtracking": "Backtracking",
    "greedy": "Greedy Algorithms",
    "greedy algorithms": "Greedy Algorithms",
    "dp": "Dynamic Programming",
    "dynamic programming": "Dynamic Programming",
    "bit manipulation": "Bit Manipulation",
    "bitwise": "Bit Manipulation",
    "interval": "Intervals",
    "intervals": "Intervals",
    "prefix sum": "Prefix Sum",
    "prefix sums": "Prefix Sum",
    "sorting": "Sorting",
    "sort": "Sorting",
    "math": "Math",
    "mathematics": "Math",
}

# Known pattern/subtopic relationships. These let us preserve the richer
# taxonomy for later skill-graph work without forcing every imported tag into
# a single root topic today.
TOPIC_HIERARCHY = {
    "Arrays & Strings": {
        "subtopics": {"Subarrays", "Strings", "Array Traversal"},
        "patterns": {"Two Pointers", "Sliding Window", "Prefix Sum", "Sorting"},
    },
    "Hashing & Hash Maps": {
        "subtopics": {"Frequency Counting", "Lookup", "Deduplication"},
        "patterns": {"Prefix Sum", "Two Pointers"},
    },
    "Binary Search": {
        "subtopics": {"Search Space", "Lower/Upper Bound"},
        "patterns": {"Binary Search"},
    },
    "Linked Lists": {
        "subtopics": {"Singly Linked List", "Doubly Linked List", "Cycle Detection"},
        "patterns": {"Two Pointers"},
    },
    "Trees & BST": {
        "subtopics": {"Binary Tree", "BST", "Tree Traversal"},
        "patterns": {"DFS", "BFS"},
    },
    "Graphs (BFS/DFS)": {
        "subtopics": {"Traversal", "Connectivity", "Shortest Path"},
        "patterns": {"BFS", "DFS"},
    },
    "Dynamic Programming": {
        "subtopics": {"1D DP", "2D DP", "Knapsack", "State Transitions"},
        "patterns": {"Memoization", "Tabulation"},
    },
}

_DIFFICULTY_ALIASES = {
    "easy": "Easy",
    "beginner": "Easy",
    "basic": "Easy",
    "1": "Easy",
    "medium": "Medium",
    "intermediate": "Medium",
    "2": "Medium",
    "hard": "Hard",
    "advanced": "Hard",
    "difficult": "Hard",
    "3": "Hard",
}


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_difficulty(value: Any) -> str | None:
    normalized = normalize_text(value).lower()
    return _DIFFICULTY_ALIASES.get(normalized)


def normalize_topic(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", normalize_text(value).lower()).strip()
    if not normalized:
        return ""
    alias = _TOPIC_ALIASES.get(normalized)
    if alias:
        return alias
    for canonical in CANONICAL_TOPICS:
        if normalized == re.sub(r"[^a-z0-9]+", " ", canonical.lower()).strip():
            return canonical
    # Preserve unknown imported tags in a readable stable form. These can be
    # mapped into the hierarchy later without silently deleting information.
    return normalize_text(value)


def canonicalize_topics(values: Iterable[Any] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values or []:
        topic = normalize_topic(value)
        if not topic:
            continue
        if topic not in seen:
            seen.add(topic)
            result.append(topic)

    return result


def is_english_problem(title: Any, description: Any) -> bool:
    return not CJK_RE.search(f"{title or ''}\n{description or ''}")



_EXAMPLES_SECTION_PATTERNS = (
    re.compile(
        r"(?is)\bexamples?\s*:?[ \t]*(?=(?:(?:example\s*\d+\s*[:.)-]?\s*)|(?:\d+[.\):-]\s*)|(?:[-*]\s*))?input\b)",
    ),
)


def strip_examples_from_description(description: Any, examples: Any = None) -> str:
    """Remove inline example sections from the problem statement."""
    text = str(description or "").strip()
    if not text:
        return ""

    cut_positions = []
    for pattern in _EXAMPLES_SECTION_PATTERNS:
        match = pattern.search(text)
        if match and match.start() > 20:
            cut_positions.append(match.start())

    if cut_positions:
        text = text[: min(cut_positions)].rstrip()

    return normalize_text(text)


def _valid_example(example: Any) -> bool:
    if not isinstance(example, dict):
        return False
    input_value = example.get("input")
    output_value = example.get("output")
    return (
        input_value is not None
        and output_value is not None
        and normalize_text(input_value) != ""
        and normalize_text(output_value) != ""
    )


def _valid_test_case(case: Any) -> bool:
    if not isinstance(case, dict):
        return False

    if "args" in case:
        expected = case.get("expected", case.get("expected_output"))
        return case.get("args") is not None and expected is not None

    return (
        normalize_text(case.get("input")) != ""
        and normalize_text(case.get("expected_output", case.get("output"))) != ""
    )


def has_valid_tests(test_cases: Any) -> bool:
    return isinstance(test_cases, list) and any(_valid_test_case(case) for case in test_cases)


def has_starter_code(starter_code: Any) -> bool:
    if not isinstance(starter_code, dict):
        return False
    return any(isinstance(value, str) and value.strip() for value in starter_code.values())


def quality_flags(problem: dict[str, Any]) -> list[str]:
    flags: list[str] = []

    title = normalize_text(problem.get("title"))
    description = normalize_text(problem.get("description"))
    difficulty = normalize_difficulty(problem.get("difficulty"))
    topics = canonicalize_topics(problem.get("topics"))
    examples = problem.get("examples")
    tests = problem.get("test_cases")
    starter_code = problem.get("starter_code")
    source = normalize_text(problem.get("source"))

    if not title:
        flags.append("missing_title")
    elif len(title) < 3:
        flags.append("invalid_title")

    if not description:
        flags.append("missing_description")
    elif len(description) < 40:
        flags.append("description_too_short")

    if not is_english_problem(title, description):
        flags.append("non_english")

    if difficulty is None:
        flags.append("unknown_difficulty")

    if not topics:
        flags.append("missing_topics")

    if not source:
        flags.append("missing_source")

    if not isinstance(examples, list) or not examples:
        flags.append("missing_examples")
    elif any(not _valid_example(example) for example in examples):
        flags.append("broken_examples")

    if not has_valid_tests(tests):
        flags.append("missing_or_invalid_tests")

    if not has_starter_code(starter_code):
        flags.append("missing_starter_code")

    return flags


def _content_fingerprint(problem: dict[str, Any]) -> str:
    title = normalize_text(problem.get("title")).lower()
    description = normalize_text(problem.get("description")).lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", f"{title} {description}").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _external_fingerprint(problem: dict[str, Any]) -> str | None:
    source = normalize_text(problem.get("source")).lower()
    external_id = normalize_text(problem.get("external_id")).lower()
    if not source or not external_id:
        return None
    return hashlib.sha256(
        f"external:{source}:{external_id}".encode("utf-8")
    ).hexdigest()


def duplicate_fingerprint(problem: dict[str, Any]) -> str:
    return _external_fingerprint(problem) or _content_fingerprint(problem)


def audit_problems(problems: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(problems)
    issue_counts: Counter[str] = Counter()
    fingerprints: dict[str, dict[str, list[str]]] = {
        "external": defaultdict(list),
        "content": defaultdict(list),
    }

    clean = 0
    for problem in items:
        flags = quality_flags(problem)
        issue_counts.update(flags)

        if not flags:
            clean += 1

        label = normalize_text(problem.get("slug")) or normalize_text(problem.get("title"))
        external = _external_fingerprint(problem)
        if external:
            fingerprints["external"][external].append(label)
        fingerprints["content"][_content_fingerprint(problem)].append(label)

    external_duplicates = {
        key: labels
        for key, labels in fingerprints["external"].items()
        if len(labels) > 1
    }
    content_duplicates = {
        key: labels
        for key, labels in fingerprints["content"].items()
        if len(labels) > 1
    }

    duplicate_groups = {
        "external_id": external_duplicates,
        "same_content": content_duplicates,
    }
    duplicate_count = sum(len(groups) for groups in duplicate_groups.values())
    if duplicate_count:
        issue_counts["duplicates"] = duplicate_count

    return {
        "total": len(items),
        "clean": clean,
        "issues": dict(sorted(issue_counts.items())),
        "duplicates": duplicate_groups,
    }


def ensure_starter_code(
    starter_code: Any,
    execution_mode: str | None = None,
) -> dict[str, str]:
    existing = starter_code if isinstance(starter_code, dict) else {}
    mode = "stdio" if str(execution_mode or "").strip().lower() == "stdio" else "function"
    defaults = STDIO_STARTERS if mode == "stdio" else FUNCTION_STARTERS

    result: dict[str, str] = {}
    for language in SUPPORTED_LANGUAGES:
        value = existing.get(language)
        result[language] = value if isinstance(value, str) and value.strip() else defaults[language]
    return result


def normalize_problem_record(problem: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(problem)

    normalized["title"] = normalize_text(problem.get("title"))
    normalized["description"] = strip_examples_from_description(
        problem.get("description"),
        problem.get("examples"),
    )
    normalized["difficulty"] = normalize_difficulty(problem.get("difficulty"))
    normalized["topics"] = canonicalize_topics(problem.get("topics"))
    normalized["source"] = normalize_text(problem.get("source")) or "imported"
    normalized["execution_mode"] = (
        "stdio"
        if str(problem.get("execution_mode") or "").strip().lower() == "stdio"
        else "function"
    )
    normalized["starter_code"] = ensure_starter_code(
        problem.get("starter_code"),
        normalized["execution_mode"],
    )

    external_id = problem.get("external_id")
    normalized["external_id"] = normalize_text(external_id) or None

    if isinstance(problem.get("external_url"), str):
        normalized["external_url"] = problem["external_url"].strip() or None

    return normalized
