from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter, defaultdict
from keyword import iskeyword
from typing import Any, Iterable

from backend.stdio_adapter import (
    editor_schema_from_metadata,
    generate_stdio_editor_starters,
    infer_editor_input_schema,
    normalize_editor_input_schema,
)

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
        "def solve(*args):\n"
        "    # Implement the required solution.\n"
        "    pass\n"
    ),
    "C++": (
        "#include <bits/stdc++.h>\n"
        "using namespace std;\n\n"
        "int solve() {\n"
        "    // Implement the required solution.\n"
        "    return 0;\n"
        "}\n"
    ),
    "Java": (
        "class Solution {\n"
        "    public int solve() {\n"
        "        // Implement the required solution.\n"
        "        return 0;\n"
        "    }\n"
        "}\n"
    ),
    "JavaScript": (
        "function solve(...args) {\n"
        "    // Implement the required solution.\n"
        "    return null;\n"
        "}\n"
    ),
    "TypeScript": (
        "function solve(...args: any[]): any {\n"
        "    // Implement the required solution.\n"
        "    return null;\n"
        "}\n"
    ),
    "Go": (
        "package main\n\n"
        "func solve(args ...interface{}) interface{} {\n"
        "    // Implement the required solution.\n"
        "    return nil\n"
        "}\n"
    ),
    "Rust": (
        "fn solve(args: &[String]) -> String {\n"
        "    // Implement the required solution.\n"
        "    String::new()\n"
        "}\n"
    ),
}


_UNIVERSAL_PARAMETER_KEYWORDS = {
    # Python
    "and", "as", "assert", "async", "await", "break", "case", "class",
    "continue", "def", "del", "elif", "else", "except", "False", "finally",
    "for", "from", "global", "if", "import", "in", "is", "lambda", "match",
    "None", "nonlocal", "not", "or", "pass", "raise", "return", "True", "try",
    "type", "while", "with", "yield",
    # C/C++/Java/JavaScript/TypeScript/Go/Rust common reserved words.
    "alignas", "alignof", "asm", "auto", "bool", "case", "catch", "char",
    "const", "constexpr", "consteval", "constinit", "const_cast", "default",
    "delete", "do", "double", "dynamic_cast", "enum", "explicit", "export",
    "extern", "false", "final", "float", "friend", "goto", "inline", "int",
    "interface", "long", "namespace", "new", "noexcept", "nullptr", "operator",
    "package", "private", "protected", "public", "register", "reinterpret_cast",
    "requires", "short", "signed", "sizeof", "static", "static_assert",
    "static_cast", "struct", "switch", "template", "this", "thread_local",
    "throw", "true", "try", "typedef", "typename", "union", "unsigned",
    "using", "virtual", "void", "volatile", "wchar_t", "abstract", "boolean",
    "byte", "extends", "final", "implements", "instanceof", "native", "strictfp",
    "super", "synchronized", "throws", "transient", "var", "volatile",
    "package", "function", "let", "of", "static", "switch", "typeof", "var",
    "with", "yield", "delete", "debugger", "constructor", "module", "select",
    "chan", "defer", "fallthrough", "go", "map", "range", "struct", "func",
    "crate", "dyn", "impl", "loop", "mod", "move", "mut", "pub", "ref", "self",
    "Self", "trait", "unsafe", "use", "where", "extern", "async", "await",
}

def _safe_function_parameter_names(names: Iterable[Any]) -> list[str]:
    """Return deterministic parameter names valid in every supported editor language."""
    result: list[str] = []
    used: set[str] = set()

    for index, raw in enumerate(names, start=1):
        original = str(raw or "").strip()
        name = re.sub(r"[^A-Za-z0-9_]", "_", original)
        if not name or not re.match(r"[A-Za-z_]", name):
            name = f"arg{index}"

        if iskeyword(name) or name in _UNIVERSAL_PARAMETER_KEYWORDS:
            name = f"{name}_"

        if not name or name in used or iskeyword(name) or name in _UNIVERSAL_PARAMETER_KEYWORDS:
            base = f"arg{index}"
            name = base
            suffix = 2
            while name in used or iskeyword(name) or name in _UNIVERSAL_PARAMETER_KEYWORDS:
                name = f"{base}_{suffix}"
                suffix += 1

        used.add(name)
        result.append(name)

    return result


def _function_parameter_names(starter: Any) -> list[str]:
    """Extract solve(...) parameter names, including from syntactically invalid legacy starters."""
    if not isinstance(starter, str) or not starter.strip():
        return []

    try:
        tree = ast.parse(starter)
    except (SyntaxError, TypeError, ValueError):
        match = re.search(r"(?m)\bdef\s+solve\s*\(([^)]*)\)", starter)
        if not match:
            return []

        names: list[str] = []
        for parameter in match.group(1).split(","):
            token = parameter.strip().lstrip("*").split(":", 1)[0].split("=", 1)[0].strip()
            if re.fullmatch(r"[A-Za-z_]\w*", token):
                names.append(token)
        return names

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "solve":
            names = [arg.arg for arg in node.args.posonlyargs]
            names.extend(arg.arg for arg in node.args.args)
            names.extend(arg.arg for arg in node.args.kwonlyargs)
            return [name for name in names if name]
    return []

def _example_parameter_names(examples: Any) -> list[str]:
    """Extract parameter names from assignment-style example inputs."""
    if not isinstance(examples, list):
        return []
    for example in examples:
        if not isinstance(example, dict):
            continue
        value = example.get("input")
        if not isinstance(value, str):
            continue
        names = re.findall(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=", value)
        if names:
            return list(dict.fromkeys(names))
    return []


def _is_generic_function_starter(language: str, source: Any) -> bool:
    if not isinstance(source, str) or not source.strip():
        return True
    normalized = source.replace(" ", "").replace("\t", "")
    signatures = {
        "Python": ("defsolve(*args):", "defsolve(**kwargs):"),
        "C++": ("intsolve(){", "longlongsolve(){"),
        "Java": ("intsolve(){", "publicintsolve(){", "longsolve(){", "publiclongsolve(){"),
        "JavaScript": ("functionsolve(...args){",),
        "TypeScript": ("functionsolve(...args:any[]):any{",),
        "Go": ("funcsolve(args...interface{})interface{}{",),
        "Rust": ("fnsolve(args:&[String])->String{",),
    }
    return any(signature in normalized for signature in signatures.get(language, ()))



def _argument_values(test_cases: Any, count: int) -> list[Any]:
    if not isinstance(test_cases, list):
        return [None] * count
    for case in test_cases:
        if not isinstance(case, dict) or "args" not in case:
            continue
        args = case.get("args")
        if not isinstance(args, list):
            continue
        normalized_args = list(args)
        if (
            count > 1
            and len(normalized_args) == 1
            and isinstance(normalized_args[0], list)
            and len(normalized_args[0]) == count
        ):
            normalized_args = list(normalized_args[0])
        return normalized_args[:count] + [None] * max(0, count - len(normalized_args))
    return [None] * count


def _schema_type_from_value(value: Any) -> str:
    if isinstance(value, bool) or isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return "string_array"
        if any(isinstance(item, float) for item in value):
            return "float_array"
        return "int_array"
    return "raw_string"


def function_editor_schema_from_problem(
    starter_code: Any,
    test_cases: Any = None,
    examples: Any = None,
    description: Any = None,
    explicit_schema: Any = None,
) -> list[dict[str, Any]]:
    """Build the callable parameter contract exposed to every language editor."""
    explicit = normalize_editor_input_schema(explicit_schema)
    names = _function_parameter_names(
        (starter_code or {}).get("Python") if isinstance(starter_code, dict) else None
    )
    if not names:
        names = _example_parameter_names(examples)
    if not names and description:
        inferred = infer_editor_input_schema(
            description,
            examples,
            explicit_schema=explicit,
        )
        names = [item["name"] for item in inferred if item["name"] != "input_data"]

    if not names and explicit:
        names = [item["name"] for item in explicit if item["name"]]
    names = _safe_function_parameter_names(names)

    values = _argument_values(test_cases, len(names))
    schema: list[dict[str, Any]] = []
    for name, value in zip(names, values):
        kind = _schema_type_from_value(value)
        if kind == "raw_string":
            kind = "string"
        schema.append({"name": name, "type": kind})
    return normalize_editor_input_schema(schema)


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
        return "int64"
    if isinstance(value, float):
        return "float64"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        inner = _inferred_go_type(value[0]) if value else "int64"
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
        return "String"
    if isinstance(value, list):
        inner = _inferred_rust_type(value[0]) if value else "i64"
        return f"Vec<{inner}>"
    return "String"


def _starter_matches_function_contract(
    language: str,
    source: Any,
    names: list[str],
) -> bool:
    if not isinstance(source, str) or not source.strip() or not names:
        return False

    compact = source.replace(" ", "").replace("\t", "").replace("\r", "")
    if language == "Python":
        actual = _function_parameter_names(source)
        return actual == names

    match = re.search(r"solve\s*\(([^)]*)\)", source)
    if not match:
        return False

    signature = match.group(1)
    return all(
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", signature)
        for name in names
    )


def _generated_function_starters(
    names: list[str],
    values: list[Any],
) -> dict[str, str]:
    if not names:
        return {language: FUNCTION_STARTERS[language] for language in SUPPORTED_LANGUAGES}

    cpp_params = ", ".join(
        f"const {_inferred_cpp_type(value)}& {name}" if isinstance(value, list)
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
        "Python": f"def solve({', '.join(names)}):\n    # Implement the required solution.\n    pass\n",
        "C++": f"#include <bits/stdc++.h>\nusing namespace std;\n\nauto solve({cpp_params}) {{\n    // Implement the required solution.\n    return 0;\n}}\n",
        "Java": f"class Solution {{\n    public Object solve({java_params}) {{\n        // Implement the required solution.\n        return 0L;\n    }}\n}}\n",
        "JavaScript": f"function solve({js_params}) {{\n    // Implement the required solution.\n    return null;\n}}\n",
        "TypeScript": f"function solve({', '.join(f'{name}: any' for name in names)}): any {{\n    // Implement the required solution.\n    return null;\n}}\n",
        "Go": f"package main\n\nfunc solve({go_params}) any {{\n    // Implement the required solution.\n    return int64(0)\n}}\n",
        "Rust": f"fn solve({rust_params}) -> impl std::fmt::Debug {{\n    // Implement the required solution.\n    0i64\n}}\n",
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


def infer_execution_mode(
    execution_mode: Any,
    test_cases: Any = None,
    starter_code: Any = None,
    examples: Any = None,
) -> str:
    """Determine whether a problem is function-style or stdin/stdout.

    Function-style is authoritative when the judge contract contains callable
    arguments or a real solve(...) signature. This also repairs legacy database
    rows that were incorrectly persisted as stdio.
    """
    explicit = str(execution_mode or "").strip().lower()
    cases_have_args = (
        isinstance(test_cases, list)
        and any(isinstance(case, dict) and "args" in case for case in test_cases)
    )
    python_names = _function_parameter_names(
        (starter_code or {}).get("Python") if isinstance(starter_code, dict) else None
    )
    example_names = _example_parameter_names(examples)

    if cases_have_args or python_names or example_names:
        return "function"
    if explicit == "stdio":
        return "stdio"
    return "function"


def ensure_starter_code(
    starter_code: Any,
    execution_mode: str | None = None,
    test_cases: Any = None,
    examples: Any = None,
    editor_schema: Any = None,
) -> dict[str, str]:
    existing = starter_code if isinstance(starter_code, dict) else {}
    mode = infer_execution_mode(
        execution_mode,
        test_cases=test_cases,
        starter_code=existing,
        examples=examples,
    )

    schema = normalize_editor_input_schema(editor_schema)
    if mode == "stdio" and not schema:
        generated = STDIO_STARTERS
        preserve_existing = True
    elif mode == "stdio":
        generated = generate_stdio_editor_starters(schema)
        preserve_existing = False
    else:
        names = _function_parameter_names(existing.get("Python"))
        if not names or _is_generic_function_starter("Python", existing.get("Python")):
            names = _example_parameter_names(examples)
        if not names:
            schema_for_names = normalize_editor_input_schema(editor_schema)
            names = [item["name"] for item in schema_for_names if item["name"] != "input_data"]
        names = _safe_function_parameter_names(names)
        values = _argument_values(test_cases, len(names))
        generated = _generated_function_starters(names, values)
        # Rebuild every function starter from the canonical problem contract so
        # old generic or mismatched language signatures cannot leak to the editor.
        preserve_existing = not bool(names)

    result: dict[str, str] = {}
    for language in SUPPORTED_LANGUAGES:
        value = existing.get(language)
        if (
            preserve_existing
            and isinstance(value, str)
            and value.strip()
            and (
                mode == "stdio"
                or not names
                or _starter_matches_function_contract(language, value, names)
            )
        ):
            result[language] = value
        else:
            result[language] = generated.get(language, "")
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
    normalized["execution_mode"] = infer_execution_mode(
        problem.get("execution_mode"),
        test_cases=problem.get("test_cases"),
        starter_code=problem.get("starter_code"),
        examples=problem.get("examples"),
    )
    editor_schema = (
        editor_schema_from_metadata(
            problem.get("package_metadata") or {},
            problem.get("description"),
            problem.get("examples"),
        )
        if normalized["execution_mode"] == "stdio"
        else function_editor_schema_from_problem(
            problem.get("starter_code"),
            problem.get("test_cases"),
            problem.get("examples"),
            problem.get("description"),
            explicit_schema=(problem.get("package_metadata") or {}).get("editor_input_schema"),
        )
    )
    normalized["editor_input_schema"] = editor_schema
    normalized["starter_code"] = ensure_starter_code(
        problem.get("starter_code"),
        normalized["execution_mode"],
        problem.get("test_cases"),
        problem.get("examples"),
        editor_schema=editor_schema,
    )

    external_id = problem.get("external_id")
    normalized["external_id"] = normalize_text(external_id) or None

    if isinstance(problem.get("external_url"), str):
        normalized["external_url"] = problem["external_url"].strip() or None

    return normalized
