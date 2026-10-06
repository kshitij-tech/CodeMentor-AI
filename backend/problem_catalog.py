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

CATALOG_FORMAT_VERSION = "2026-10"

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
    "package", "function", "let", "static", "switch", "typeof", "var",
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



def _argument_values(
    test_cases: Any,
    count: int,
    schema: Any = None,
) -> list[Any]:
    normalized_schema = normalize_editor_input_schema(schema)
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
        elif (
            count == 1
            and len(normalized_args) == 1
            and isinstance(normalized_args[0], list)
            and len(normalized_args[0]) == 1
            and normalized_schema
            and not str(normalized_schema[0].get("type", "")).endswith("_array")
        ):
            # Some imported function cases historically wrapped a single
            # scalar/string argument in one extra list layer.
            normalized_args = [normalized_args[0][0]]
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

    values = _argument_values(test_cases, len(names), explicit)
    schema: list[dict[str, Any]] = []
    explicit_types = [item["type"] for item in explicit]
    for index, (name, value) in enumerate(zip(names, values)):
        kind = explicit_types[index] if index < len(explicit_types) else _schema_type_from_value(value)
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

USER_IO_STARTERS = {
    "Python": (
        "import sys\n\n"
        "# Read the complete test input from standard input.\n"
        "input_data = sys.stdin.read()\n\n"
        "# Parse input_data according to the problem statement.\n"
        "# Compute the answer and print it.\n"
        "result = None\n"
        "print(result)\n"
    ),
    "C++": (
        "#include <bits/stdc++.h>\n"
        "using namespace std;\n\n"
        "int main() {\n"
        "    ios::sync_with_stdio(false);\n"
        "    cin.tie(nullptr);\n\n"
        "    // Read the test input from standard input.\n"
        "    // Parse it according to the problem statement.\n"
        "    // Compute the answer and print it.\n"
        "    return 0;\n"
        "}\n"
    ),
    "Java": (
        "import java.io.*;\n"
        "import java.util.*;\n\n"
        "public class Main {\n"
        "    public static void main(String[] args) throws Exception {\n"
        "        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));\n"
        "        StringBuilder sb = new StringBuilder();\n"
        "        String line;\n"
        "        while ((line = br.readLine()) != null) sb.append(line).append('\\n');\n\n"
        "        // Parse input according to the problem statement.\n"
        "        // Compute the answer and print it.\n"
        "        System.out.println();\n"
        "    }\n"
        "}\n"
    ),
    "JavaScript": (
        "const fs = require('fs');\n\n"
        "const input = fs.readFileSync(0, 'utf8');\n\n"
        "// Parse input according to the problem statement.\n"
        "// Compute the answer and print it.\n"
        "const result = '';\n"
        "process.stdout.write(String(result));\n"
    ),
    "TypeScript": (
        "declare const require: (name: string) => any;\n"
        "const fs: any = require('fs');\n\n"
        "const input: string = fs.readFileSync(0, 'utf8');\n\n"
        "// Parse input according to the problem statement.\n"
        "// Compute the answer and print it.\n"
        "const result: any = '';\n"
        "process.stdout.write(String(result));\n"
    ),
    "Go": (
        "package main\n\n"
        "import (\n"
        "    \"fmt\"\n"
        "    \"io\"\n"
        "    \"os\"\n"
        ")\n\n"
        "func main() {\n"
        "    inputBytes, err := io.ReadAll(os.Stdin)\n"
        "    if err != nil {\n"
        "        panic(err)\n"
        "    }\n"
        "    input := string(inputBytes)\n"
        "    _ = input\n\n"
        "    // Parse input according to the problem statement.\n"
        "    // Compute the answer and print it.\n"
        "    fmt.Println()\n"
        "}\n"
    ),
    "Rust": (
        "use std::io::{self, Read};\n\n"
        "fn main() {\n"
        "    let mut input = String::new();\n"
        "    io::stdin().read_to_string(&mut input).unwrap();\n\n"
        "    // Parse input according to the problem statement.\n"
        "    // Compute the answer and print it.\n"
        "    println!();\n"
        "}\n"
    ),
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
    "Arrays", "Strings", "Hashing", "Two Pointers", "Sliding Window",
    "Stack", "Queue", "Linked List", "Binary Search", "Trees", "BST",
    "Heap/Priority Queue", "Graphs", "DFS", "BFS", "Backtracking", "Greedy",
    "Dynamic Programming", "Bit Manipulation", "Math", "Intervals", "Sorting",
    "Recursion", "Prefix Sum", "Trie", "Union Find", "Topological Sort",
    "Divide and Conquer", "Monotonic Stack", "Monotonic Queue", "Matrix",
    "Implementation", "Brute Force", "Constructive Algorithms", "Number Theory",
    "Combinatorics", "Geometry", "Probability", "Game Theory", "Meet in the Middle",
)

_TOPIC_ALIASES = {
    "array": "Arrays", "arrays": "Arrays", "string": "Strings", "strings": "Strings",
    "hashing": "Hashing", "hash table": "Hashing", "hash tables": "Hashing",
    "hash map": "Hashing", "hash maps": "Hashing", "map": "Hashing", "maps": "Hashing",
    "unordered map": "Hashing", "data structures": "Hashing",
    "two pointer": "Two Pointers", "two pointers": "Two Pointers",
    "two-pointer": "Two Pointers", "two-pointers": "Two Pointers",
    "sliding window": "Sliding Window", "sliding-window": "Sliding Window",
    "binary search": "Binary Search", "binary_search": "Binary Search",
    "linked list": "Linked List", "linked lists": "Linked List",
    "linked-list": "Linked List", "linked-lists": "Linked List",
    "stack": "Stack", "stacks": "Stack", "queue": "Queue", "queues": "Queue",
    "tree": "Trees", "trees": "Trees", "binary tree": "Trees",
    "bst": "BST", "binary search tree": "BST",
    "heap": "Heap/Priority Queue", "heaps": "Heap/Priority Queue",
    "priority queue": "Heap/Priority Queue", "priority queues": "Heap/Priority Queue",
    "graph": "Graphs", "graphs": "Graphs", "bfs": "BFS", "dfs": "DFS",
    "shortest path": "Graphs", "shortest paths": "Graphs",
    "backtracking": "Backtracking", "greedy": "Greedy", "greedy algorithms": "Greedy",
    "dp": "Dynamic Programming", "dynamic programming": "Dynamic Programming",
    "bit manipulation": "Bit Manipulation", "bitwise": "Bit Manipulation",
    "interval": "Intervals", "intervals": "Intervals", "prefix sum": "Prefix Sum",
    "prefix sums": "Prefix Sum", "sorting": "Sorting", "sort": "Sorting",
    "math": "Math", "mathematics": "Math", "recursion": "Recursion", "recursive": "Recursion",
    "trie": "Trie", "union find": "Union Find", "disjoint set union": "Union Find", "dsu": "Union Find",
    "topological sort": "Topological Sort", "topological sorting": "Topological Sort",
    "divide and conquer": "Divide and Conquer", "monotonic stack": "Monotonic Stack",
    "monotonic queue": "Monotonic Queue", "matrix": "Matrix", "matrices": "Matrix",
    "implementation": "Implementation", "input output": "Implementation", "io": "Implementation",
    "brute force": "Brute Force",
    "constructive algorithms": "Constructive Algorithms", "number theory": "Number Theory",
    "combinatorics": "Combinatorics", "geometry": "Geometry", "probability": "Probability",
    "game theory": "Game Theory", "games": "Game Theory", "meet in the middle": "Meet in the Middle",
}

_TOPIC_EXPANSIONS = {
    "arrays strings": ["Arrays", "Strings"],
    "hashing hash maps": ["Hashing"],
    "stacks queues": ["Stack", "Queue"],
    "trees bst": ["Trees", "BST"],
    "heaps priority queues": ["Heap/Priority Queue"],
    "graphs bfs dfs": ["Graphs", "BFS", "DFS"],
    "linked lists": ["Linked List"],
    "greedy algorithms": ["Greedy"],
    "dynamic programming": ["Dynamic Programming"],
    "bit manipulation": ["Bit Manipulation"],
}

TOPIC_HIERARCHY = {
    "Arrays": {"subtopics": {"Traversal", "Subarrays", "Prefix Techniques"}, "patterns": {"Two Pointers", "Sliding Window", "Prefix Sum", "Sorting"}},
    "Strings": {"subtopics": {"Parsing", "Frequency", "Pattern Matching"}, "patterns": {"Two Pointers", "Sliding Window", "Hashing"}},
    "Hashing": {"subtopics": {"Frequency Counting", "Lookup", "Deduplication"}, "patterns": {"Prefix Sum", "Two Pointers"}},
    "Two Pointers": {"subtopics": {"Opposing Pointers", "Same-Direction Pointers", "Partitioning"}, "patterns": {"Sorting", "Sliding Window"}},
    "Sliding Window": {"subtopics": {"Fixed Window", "Variable Window"}, "patterns": {"Two Pointers", "Hashing"}},
    "Stack": {"subtopics": {"Monotonic Stack", "Expression Parsing"}, "patterns": {"DFS", "Backtracking"}},
    "Queue": {"subtopics": {"Deque", "Monotonic Queue"}, "patterns": {"BFS", "Sliding Window"}},
    "Linked List": {"subtopics": {"Singly Linked List", "Doubly Linked List", "Cycle Detection"}, "patterns": {"Two Pointers"}},
    "Binary Search": {"subtopics": {"Search Space", "Lower Bound", "Upper Bound"}, "patterns": {"Two Pointers"}},
    "Trees": {"subtopics": {"Binary Tree", "Traversal", "Path Problems"}, "patterns": {"DFS", "BFS", "Recursion"}},
    "BST": {"subtopics": {"Ordering", "Range Queries", "Validation"}, "patterns": {"Binary Search", "DFS"}},
    "Heap/Priority Queue": {"subtopics": {"Min Heap", "Max Heap", "Top K"}, "patterns": {"Greedy", "Graphs"}},
    "Graphs": {"subtopics": {"Connectivity", "Shortest Path", "Components"}, "patterns": {"BFS", "DFS", "Union Find"}},
    "DFS": {"subtopics": {"Recursive DFS", "Iterative DFS"}, "patterns": {"Trees", "Graphs", "Backtracking"}},
    "BFS": {"subtopics": {"Level Traversal", "Shortest Unweighted Path"}, "patterns": {"Trees", "Graphs", "Queue"}},
    "Backtracking": {"subtopics": {"Permutations", "Combinations", "Constraint Search"}, "patterns": {"Recursion", "DFS"}},
    "Greedy": {"subtopics": {"Exchange Argument", "Local Choice"}, "patterns": {"Sorting", "Intervals", "Heap/Priority Queue"}},
    "Dynamic Programming": {"subtopics": {"1D DP", "2D DP", "Knapsack", "State Transitions"}, "patterns": {"Memoization", "Tabulation"}},
    "Bit Manipulation": {"subtopics": {"Bit Masks", "XOR", "Bit Counting"}, "patterns": {"Math"}},
    "Math": {"subtopics": {"Arithmetic", "Number Theory", "Combinatorics"}, "patterns": {"Bit Manipulation"}},
    "Intervals": {"subtopics": {"Merging", "Scheduling", "Sweep Line"}, "patterns": {"Sorting", "Greedy"}},
    "Sorting": {"subtopics": {"Comparison Sorts", "Counting Sort", "Custom Ordering"}, "patterns": {"Greedy", "Binary Search"}},
    "Recursion": {"subtopics": {"Recursive State", "Base Cases"}, "patterns": {"DFS", "Backtracking", "Dynamic Programming"}},
    "Prefix Sum": {"subtopics": {"1D Prefix Sum", "2D Prefix Sum", "Difference Array"}, "patterns": {"Hashing", "Dynamic Programming"}},
    "Trie": {"subtopics": {"Prefix Queries", "String Dictionary"}, "patterns": {"Strings"}},
    "Union Find": {"subtopics": {"Components", "Cycle Detection", "Kruskal"}, "patterns": {"Graphs"}},
    "Topological Sort": {"subtopics": {"Kahn's Algorithm", "Dependency Ordering"}, "patterns": {"BFS", "DFS", "Graphs"}},
    "Divide and Conquer": {"subtopics": {"Merge Decomposition", "Recursive Partitioning"}, "patterns": {"Recursion", "Sorting"}},
    "Monotonic Stack": {"subtopics": {"Next Greater", "Next Smaller"}, "patterns": {"Stack"}},
    "Monotonic Queue": {"subtopics": {"Sliding Maximum", "Sliding Minimum"}, "patterns": {"Queue", "Sliding Window"}},
    "Matrix": {"subtopics": {"Grid Traversal", "2D Prefix Sum"}, "patterns": {"DFS", "BFS", "Dynamic Programming"}},
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


def _topic_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(value).lower()).strip()


def _topic_values(value: Any) -> list[str]:
    key = _topic_key(value)
    if not key:
        return []
    if key in _TOPIC_EXPANSIONS:
        return list(_TOPIC_EXPANSIONS[key])
    alias = _TOPIC_ALIASES.get(key)
    if alias:
        return [alias]
    for canonical in CANONICAL_TOPICS:
        if key == _topic_key(canonical):
            return [canonical]
    return []


def invalid_topic_names(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        return [normalize_text(values) or "<invalid>"]
    invalid: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalize_text(value)
        if not text:
            invalid.append("<empty>")
        elif not _topic_values(value) and text not in seen:
            invalid.append(text)
            seen.add(text)
    return list(dict.fromkeys(invalid))


def normalize_difficulty(value: Any) -> str | None:
    return _DIFFICULTY_ALIASES.get(normalize_text(value).lower())


def normalize_topic(value: Any) -> str:
    values = _topic_values(value)
    return values[0] if values else ""


def canonicalize_topics(values: Iterable[Any] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    if values is None:
        return result
    iterable = values if isinstance(values, list) else [values]
    for value in iterable:
        for topic in _topic_values(value):
            if topic not in seen:
                seen.add(topic)
                result.append(topic)
    return result


def is_english_problem(title: Any, description: Any) -> bool:
    text = f"{title or ''}\n{description or ''}"
    if CJK_RE.search(text):
        return False
    if re.search(r"[\u0400-\u04FF\u0600-\u06FF\u0900-\u097F\u0370-\u03FF\uAC00-\uD7AF]", text):
        return False
    ascii_letters = len(re.findall(r"[A-Za-z]", text))
    all_letters = len(re.findall(r"[A-Za-z\u00C0-\u024F]", text))
    if ascii_letters < 8 or ascii_letters / max(all_letters, 1) < 0.88:
        return False
    tokens = set(re.findall(r"[a-z]+", text.lower()))
    markers = {"the","given","find","return","input","output","where","each","array","arrays","integer","number","string","strings","list","value","values","read","maximum","minimum","print","write","calculate","determine","contains","must","for","you","answer","problem","word","twice","permutation"}
    return len(tokens & markers) >= 2


_EXAMPLES_SECTION_PATTERNS = (
    re.compile(r"(?is)\bexamples?\s*:?[ \t]*(?=(?:(?:example\s*\d+\s*[:.)-]?\s*)|(?:\d+[.\):-]\s*)|(?:[-*]\s*))?input\b)"),
)


def strip_examples_from_description(description: Any, examples: Any = None) -> str:
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
    return (
        isinstance(example, dict)
        and isinstance(example.get("input"), str)
        and isinstance(example.get("output"), str)
        and normalize_text(example.get("input")) != ""
        and normalize_text(example.get("output")) != ""
    )


def _valid_test_case(case: Any, execution_mode: str | None = None) -> bool:
    if not isinstance(case, dict):
        return False
    if "args" in case:
        expected = "expected" if "expected" in case else "expected_output"
        return isinstance(case.get("args"), list) and expected in case and case.get(expected) is not None
    if execution_mode == "function":
        return False
    return (
        "input" in case
        and ("expected_output" in case or "output" in case)
        and isinstance(case.get("input"), str)
        and isinstance(case.get("expected_output", case.get("output")), str)
    )


def has_valid_tests(test_cases: Any, execution_mode: str | None = None) -> bool:
    return isinstance(test_cases, list) and bool(test_cases) and all(_valid_test_case(case, execution_mode) for case in test_cases)


def _starter_syntax_valid(language: str, source: Any, execution_mode: str = "function") -> bool:
    if not isinstance(source, str) or not source.strip():
        return False
    if language == "Python":
        try:
            ast.parse(source)
            return True
        except (SyntaxError, ValueError, TypeError):
            return False
    if source.count("{") != source.count("}"):
        return False
    if language == "C++":
        return bool(re.search(r"\bsolve\s*\(", source) or re.search(r"\bint\s+main\s*\(", source))
    if language == "Java":
        return "class " in source and bool(re.search(r"\b(?:solve|main)\s*\(", source))
    if language in {"JavaScript", "TypeScript"}:
        return bool(re.search(r"\bfunction\s+solve\s*\(", source) or "process.stdout.write" in source or "console.log" in source)
    if language == "Go":
        return "package main" in source and bool(re.search(r"\bfunc\s+(?:solve|main)\s*\(", source))
    if language == "Rust":
        return bool(re.search(r"\bfn\s+(?:solve|main)\s*\(", source))
    return False


def _canonicalize_editor_schema(schema: Any) -> list[dict[str, Any]]:
    normalized = normalize_editor_input_schema(schema)
    if not normalized:
        return []

    original_names = [str(item.get("name") or "") for item in normalized]
    safe_names = _safe_function_parameter_names(original_names)
    name_map = dict(zip(original_names, safe_names))

    result = []
    for item, original_name in zip(normalized, original_names):
        updated = dict(item)
        updated["name"] = name_map.get(original_name, original_name)
        length_from = updated.get("length_from")
        if length_from in name_map:
            updated["length_from"] = name_map[length_from]
        result.append(updated)
    return result


def _supported_languages(problem: dict[str, Any]) -> list[str]:
    metadata = problem.get("package_metadata") or {}
    value = problem.get("supported_languages")
    if value is None and isinstance(metadata, dict):
        value = metadata.get("supported_languages")
    return [str(item) for item in value] if isinstance(value, list) else []


def _valid_editor_schema(value: Any) -> bool:
    raw = value
    if isinstance(value, dict):
        raw = value.get("parameters") or value.get("params") or value.get("schema")
    if not isinstance(raw, list):
        return False
    normalized = normalize_editor_input_schema(raw)
    if len(normalized) != len(raw):
        return False
    names = [str(item.get("name") or "") for item in normalized]
    safe_names = _safe_function_parameter_names(names)
    if names != safe_names:
        return False
    return all(
        not item.get("length_from")
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(item["length_from"]))
        for item in normalized
    )


def extract_constraints(description: Any, metadata: Any = None) -> list[str]:
    meta = metadata if isinstance(metadata, dict) else {}
    candidates = meta.get("constraints")
    if isinstance(candidates, str):
        candidates = [line.strip() for line in candidates.splitlines() if line.strip()]
    if isinstance(candidates, list):
        cleaned = [normalize_text(item) for item in candidates if normalize_text(item)]
        if cleaned:
            return cleaned[:20]
    text = str(description or "")
    section = re.search(
        r"(?is)(?:^|\n)\s*(?:#+\s*)?constraints?\s*:?[ \t]*\n(.*?)(?=\n\s*(?:#+\s*)?(?:input|output|examples?|sample|note|explanation|solution)\b|\Z)",
        text,
    )
    if section:
        lines = []
        for line in section.group(1).splitlines():
            line = re.sub(r"^\s*[-*•]\s*", "", line).strip()
            if line and len(line) >= 2:
                lines.append(normalize_text(line))
        if lines:
            return lines[:20]
    bounds = []
    for line in text.splitlines():
        if re.search(r"(?:<=|>=|\bup to\b|at most|at least)", line, re.I) and re.search(r"\d", line):
            line = re.sub(r"^\s*[-*•]\s*", "", line).strip()
            if line:
                bounds.append(normalize_text(line))
    return list(dict.fromkeys(bounds))[:20]


def quality_flags(problem: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    title = normalize_text(problem.get("title"))
    description = strip_examples_from_description(problem.get("description"), problem.get("examples"))
    raw_topics = problem.get("topics")
    constraints = problem.get("constraints")
    examples = problem.get("examples")
    tests = problem.get("test_cases")
    starter_code = problem.get("starter_code")
    source = normalize_text(problem.get("source"))
    mode = str(problem.get("execution_mode") or "").strip().lower()
    metadata = problem.get("package_metadata") or {}

    slug = normalize_text(problem.get("slug"))
    if not slug:
        flags.append("missing_slug")
    elif not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 120:
        flags.append("invalid_slug")
    if not title:
        flags.append("missing_title")
    elif len(title) < 3:
        flags.append("invalid_title")
    if not description:
        flags.append("missing_description")
    elif len(description) < 40 or description.casefold() == title.casefold() or re.search(r"\b(?:todo|coming soon|placeholder|lorem ipsum)\b", description, re.I):
        flags.append("incomplete_statement")
    if not is_english_problem(title, description):
        flags.append("non_english")
    if normalize_difficulty(problem.get("difficulty")) is None:
        flags.append("unknown_difficulty")
    if not isinstance(raw_topics, list) or not raw_topics:
        flags.append("missing_topics")
    if invalid_topic_names(raw_topics):
        flags.append("invalid_topic_names")
    if not source:
        flags.append("missing_source")
    if not isinstance(constraints, list) or not any(isinstance(item, str) and normalize_text(item) for item in constraints):
        flags.append("missing_constraints")
    elif any(not isinstance(item, str) or not normalize_text(item) for item in constraints):
        flags.append("malformed_constraints")
    if not isinstance(examples, list) or not examples:
        flags.append("missing_examples")
    elif any(not _valid_example(example) for example in examples):
        flags.append("broken_examples")
    if not isinstance(tests, list) or not tests:
        flags.append("missing_or_invalid_tests")
    elif any(not _valid_test_case(case, mode) for case in tests):
        flags.append("broken_test_cases")
    if (
        not isinstance(starter_code, dict)
        or not any(
            isinstance(starter_code.get(language), str) and starter_code[language].strip()
            for language in SUPPORTED_LANGUAGES
        )
    ):
        flags.append("missing_starter_code")
    if not isinstance(starter_code, dict):
        pass
    else:
        missing = [language for language in SUPPORTED_LANGUAGES if not isinstance(starter_code.get(language), str) or not starter_code[language].strip()]
        broken = [language for language in SUPPORTED_LANGUAGES if language in starter_code and not _starter_syntax_valid(language, starter_code.get(language), mode)]
        if missing:
            flags.append("missing_starter_languages")
        if broken:
            flags.append("broken_starter_code")
    if mode not in {"function", "stdio"}:
        flags.append("invalid_execution_mode")
    if _supported_languages(problem) != list(SUPPORTED_LANGUAGES):
        flags.append("invalid_supported_languages")
    schema = metadata.get("editor_input_schema") if isinstance(metadata, dict) else None
    if schema is not None and not _valid_editor_schema(schema):
        flags.append("invalid_io_definition")
    if mode == "stdio" and not isinstance(schema, list):
        flags.append("invalid_io_definition")
    if mode == "stdio" and isinstance(schema, list) and not schema:
        description_text = str(problem.get("description") or "")
        has_input = bool(re.search(r"(?im)^\s*(?:#+\s*)?input\b", description_text))
        has_output = bool(re.search(r"(?im)^\s*(?:#+\s*)?output\b", description_text))
        if not has_input or not has_output:
            flags.append("invalid_io_definition")
    if isinstance(metadata, dict):
        for field in ("input_format", "output_format"):
            if field in metadata and (not isinstance(metadata[field], str) or not normalize_text(metadata[field])):
                flags.append("invalid_io_definition")
    return list(dict.fromkeys(flags))




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


def content_fingerprint(problem: dict[str, Any]) -> str:
    """Return normalized title/description identity independent of external IDs."""
    return _content_fingerprint(problem)


def audit_problems(problems: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(problems)
    base_flags = []
    groups = {"external": defaultdict(list), "content": defaultdict(list)}
    for problem in items:
        base_flags.append(quality_flags(problem))
        label = normalize_text(problem.get("slug")) or normalize_text(problem.get("title")) or "<unnamed>"
        ext = _external_fingerprint(problem)
        if ext:
            groups["external"][ext].append(label)
        groups["content"][_content_fingerprint(problem)].append(label)

    external_duplicates = {key: labels for key, labels in groups["external"].items() if len(labels) > 1}
    content_duplicates = {key: labels for key, labels in groups["content"].items() if len(labels) > 1}
    duplicate_labels = defaultdict(set)
    for labels in external_duplicates.values():
        for label in labels:
            duplicate_labels[label].add("duplicate_external_id")
    for labels in content_duplicates.values():
        for label in labels:
            duplicate_labels[label].add("duplicate_content")

    issues = Counter()
    reports = []
    clean = 0
    for problem, flags in zip(items, base_flags):
        label = normalize_text(problem.get("slug")) or normalize_text(problem.get("title")) or "<unnamed>"
        final_flags = list(dict.fromkeys(flags + sorted(duplicate_labels.get(label, set()))))
        issues.update(final_flags)
        clean += not final_flags
        reports.append({"id": problem.get("id"), "slug": problem.get("slug"), "title": problem.get("title"), "flags": final_flags})

    valid = [p for p, report in zip(items, reports) if not report["flags"]]
    topics, difficulties, languages, sources = Counter(), Counter(), Counter(), Counter()
    for problem in valid:
        topics.update(canonicalize_topics(problem.get("topics")))
        difficulty = normalize_difficulty(problem.get("difficulty"))
        if difficulty:
            difficulties[difficulty] += 1
        source = normalize_text(problem.get("source"))
        if source:
            sources[source] += 1
        languages.update(_supported_languages(problem))

    return {
        "total": len(items),
        "clean": int(clean),
        "issues": dict(sorted(issues.items())),
        "duplicates": {"external_id": external_duplicates, "same_content": content_duplicates},
        "problem_reports": reports,
        "health": {
            "quality_rate_percent": round(clean / len(items) * 100, 2) if items else 100.0,
            "topic_distribution": dict(sorted(topics.items(), key=lambda x: (-x[1], x[0]))),
            "difficulty_distribution": dict(sorted(difficulties.items())),
            "language_distribution": dict(sorted(languages.items())),
            "source_distribution": dict(sorted(sources.items())),
            "duplicate_group_count": len(external_duplicates) + len(content_duplicates),
        },
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

    # Respect an explicit mode unless the test contract proves a legacy
    # function-style record was mislabeled as stdio.
    if explicit == "function":
        return "function"
    if explicit == "stdio" and not cases_have_args:
        return "stdio"

    python_names = _function_parameter_names(
        (starter_code or {}).get("Python") if isinstance(starter_code, dict) else None
    )
    example_names = _example_parameter_names(examples)

    if cases_have_args or python_names or example_names:
        return "function"
    return "function"


def _schema_input_code(language: str, schema: list[dict[str, Any]], indent: str = "    ") -> list[str]:
    """Create simple, problem-specific stdin parsing boilerplate."""
    input_comment = f"{indent}// Input: read the values in the same order as the problem statement." if language != "Python" else f"{indent}# Input: read the values in the same order as the problem statement."
    output_comment = f"{indent}// Output: return the final answer from solve(). The runner will print it." if language != "Python" else f"{indent}# Output: return the final answer from solve(). The runner will print it."

    if not schema:
        if language == "Python":
            return [
                input_comment,
                f"{indent}input_data = sys.stdin.read()",
                f"{indent}# TODO: parse input_data according to the problem statement.",
                output_comment,
            ]
        if language == "C++":
            return [
                input_comment,
                f"{indent}string input_data((istreambuf_iterator<char>(cin)), istreambuf_iterator<char>());",
                f"{indent}// TODO: parse input_data according to the problem statement.",
                output_comment,
            ]
        if language == "Java":
            return [
                input_comment,
                f"{indent}java.util.Scanner scanner = new java.util.Scanner(System.in);",
                f"{indent}String input_data = scanner.hasNextLine() ? scanner.nextLine() : \\\"\\\";",
                f"{indent}// TODO: parse input_data according to the problem statement.",
                output_comment,
            ]
        if language in {"JavaScript", "TypeScript"}:
            return [
                input_comment,
                f"{indent}const input = fs.readFileSync(0, 'utf8');",
                f"{indent}// TODO: parse input according to the problem statement.",
                output_comment,
            ]
        if language == "Go":
            return [
                input_comment,
                f"{indent}data, _ := io.ReadAll(os.Stdin)",
                f"{indent}input := string(data)",
                f"{indent}_ = input",
                f"{indent}// TODO: parse input according to the problem statement.",
                output_comment,
            ]
        return [
            input_comment,
            f"{indent}let mut input = String::new();",
            f"{indent}std::io::stdin().read_to_string(&mut input).unwrap();",
            f"{indent}// TODO: parse input according to the problem statement.",
            output_comment,
        ]

    lines: list[str] = [input_comment]

    if language == "Python":
        for item in schema:
            name, kind = item["name"], item["type"]
            length = item.get("length_from")
            if kind == "int":
                lines.append(f"{indent}{name} = int(input())")
            elif kind == "float":
                lines.append(f"{indent}{name} = float(input())")
            elif kind == "string":
                lines.append(f"{indent}{name} = input().strip()")
            elif kind == "raw_string":
                lines.append(f"{indent}{name} = sys.stdin.read()")
            elif kind.endswith("_array") and length:
                parser = {"int_array": "int", "float_array": "float", "string_array": "str"}[kind]
                lines.append(f"{indent}{name} = list(map({parser}, input().split()))")
                lines.append(f"{indent}# {name} should contain {length} values.")
        lines.extend([
            f"{indent}# TODO: solve the problem using the input above.",
            output_comment,
        ])
        return lines

    if language == "C++":
        for item in schema:
            name, kind = item["name"], item["type"]
            length = item.get("length_from")
            if kind == "int":
                lines.append(f"{indent}long long {name};")
                lines.append(f"{indent}cin >> {name};")
            elif kind == "float":
                lines.append(f"{indent}double {name};")
                lines.append(f"{indent}cin >> {name};")
            elif kind == "string":
                lines.append(f"{indent}string {name};")
                lines.append(f"{indent}cin >> {name};")
            elif kind == "raw_string":
                lines.append(f"{indent}string {name};")
                lines.append(f"{indent}getline(cin >> ws, {name});")
            elif kind.endswith("_array") and length:
                typ = {"int_array": "long long", "float_array": "double", "string_array": "string"}[kind]
                lines.append(f"{indent}vector<{typ}> {name}({length});")
                lines.append(f"{indent}for (auto &value : {name}) cin >> value;")
        lines.extend([
            f"{indent}// TODO: solve the problem using the input above.",
            output_comment,
        ])
        return lines

    if language == "Java":
        lines.append(f"{indent}java.util.Scanner scanner = new java.util.Scanner(System.in);")
        for item in schema:
            name, kind = item["name"], item["type"]
            length = item.get("length_from")
            if kind == "int":
                lines.append(f"{indent}long {name} = scanner.nextLong();")
            elif kind == "float":
                lines.append(f"{indent}double {name} = scanner.nextDouble();")
            elif kind == "string":
                lines.append(f"{indent}String {name} = scanner.next();")
            elif kind == "raw_string":
                lines.append(f"{indent}String {name} = scanner.hasNextLine() ? scanner.nextLine() : \"\";")
            elif kind.endswith("_array") and length:
                if kind == "int_array":
                    lines.append(f"{indent}long[] {name} = new long[(int){length}];")
                    lines.append(f"{indent}for (int i = 0; i < {name}.length; i++) {name}[i] = scanner.nextLong();")
                elif kind == "float_array":
                    lines.append(f"{indent}double[] {name} = new double[(int){length}];")
                    lines.append(f"{indent}for (int i = 0; i < {name}.length; i++) {name}[i] = scanner.nextDouble();")
                else:
                    lines.append(f"{indent}String[] {name} = new String[(int){length}];")
                    lines.append(f"{indent}for (int i = 0; i < {name}.length; i++) {name}[i] = scanner.next();")
        lines.extend([
            f"{indent}// TODO: solve the problem using the input above.",
            output_comment,
        ])
        return lines

    if language in {"JavaScript", "TypeScript"}:
        lines.extend([
            f"{indent}const input = fs.readFileSync(0, 'utf8').trim().split(/\\s+/).filter(Boolean);",
            f"{indent}let index = 0;",
            f"{indent}const next = () => input[index++];",
        ])
        for item in schema:
            name, kind = item["name"], item["type"]
            length = item.get("length_from")
            if kind in {"int", "float"}:
                lines.append(f"{indent}const {name} = Number(next());")
            elif kind in {"string", "raw_string"}:
                lines.append(f"{indent}const {name} = next();")
            elif kind.endswith("_array") and length:
                lines.append(f"{indent}const {name} = Array.from({{length: Number({length})}}, () => Number(next()));" if kind != "string_array" else f"{indent}const {name} = Array.from({{length: Number({length})}}, () => next());")
        lines.extend([
            f"{indent}// TODO: solve the problem using the input above.",
            output_comment,
        ])
        return lines

    if language == "Go":
        lines.append(f"{indent}reader := bufio.NewReader(os.Stdin)")
        for item in schema:
            name, kind = item["name"], item["type"]
            length = item.get("length_from")
            if kind == "int":
                lines.append(f"{indent}var {name} int64")
                lines.append(f"{indent}fmt.Fscan(reader, &{name})")
            elif kind == "float":
                lines.append(f"{indent}var {name} float64")
                lines.append(f"{indent}fmt.Fscan(reader, &{name})")
            elif kind == "string":
                lines.append(f"{indent}var {name} string")
                lines.append(f"{indent}fmt.Fscan(reader, &{name})")
            elif kind.endswith("_array") and length:
                typ = {"int_array": "int64", "float_array": "float64", "string_array": "string"}[kind]
                lines.append(f"{indent}{name} := make([]{typ}, {length})")
                lines.append(f"{indent}for i := range {name} {{ fmt.Fscan(reader, &{name}[i]) }}")
        lines.extend([
            f"{indent}// TODO: solve the problem using the input above.",
            output_comment,
        ])
        return lines

    lines.extend([
        f"{indent}let mut input = String::new();",
        f"{indent}std::io::stdin().read_to_string(&mut input).unwrap();",
        f"{indent}let mut iter = input.split_whitespace();",
    ])
    for item in schema:
        name, kind = item["name"], item["type"]
        length = item.get("length_from")
        if kind == "int":
            lines.append(f'{indent}let {name}: i64 = iter.next().unwrap().parse().unwrap();')
        elif kind == "float":
            lines.append(f'{indent}let {name}: f64 = iter.next().unwrap().parse().unwrap();')
        elif kind == "string":
            lines.append(f'{indent}let {name} = iter.next().unwrap().to_string();')
        elif kind.endswith("_array") and length:
            typ = {"int_array": "i64", "float_array": "f64", "string_array": "String"}[kind]
            parse = {"int_array": "parse::<i64>().unwrap()", "float_array": "parse::<f64>().unwrap()", "string_array": "to_string()"}[kind]
            lines.append(f"{indent}let {name}: Vec<{typ}> = (0..{length}).map(|_| iter.next().unwrap().{parse}).collect();")
    lines.extend([
        f"{indent}// TODO: solve the problem using the input above.",
        output_comment,
    ])
    return lines


def _replace_solve_signature(source: str, language: str) -> tuple[str, bool]:
    """Remove solve(...) parameters while preserving the problem's boilerplate and body."""
    if not isinstance(source, str):
        return "", False

    patterns = {
        "Python": r"(?m)^(?P<indent>\s*)def\s+solve\s*\([^)]*\)\s*:",
        "C++": r"(?m)(?P<prefix>\bsolve)\s*\([^)]*\)\s*\{",
        "Java": r"(?m)(?P<prefix>\bsolve)\s*\([^)]*\)\s*\{",
        "JavaScript": r"(?m)(?P<prefix>function\s+solve)\s*\([^)]*\)\s*\{",
        "TypeScript": r"(?m)(?P<prefix>function\s+solve)\s*\([^)]*\)\s*\{",
        "Go": r"(?m)(?P<prefix>\bfunc\s+solve)\s*\([^)]*\)(?P<return>[^\n{]*)\{",
        "Rust": r"(?m)(?P<prefix>\bfn\s+solve)\s*\([^)]*\)(?P<return>[^\n{]*)\{",
    }
    pattern = patterns.get(language)
    if not pattern:
        return source, False

    match = re.search(pattern, source)
    if not match:
        return source, False

    if language == "Python":
        start, end = match.span()
        replacement = f"{match.group('indent')}def solve():"
        return source[:start] + replacement + source[end:], True

    replacement = re.sub(r"solve\s*\([^)]*\)", "solve()", match.group(0), count=1)
    start, end = match.span()
    return source[:start] + replacement + source[end:], True


def _insert_after_solve_opening(source: str, language: str, schema: list[dict[str, Any]]) -> str:
    if language == "Python":
        match = re.search(r"(?m)^\s*def\s+solve\(\)\s*:", source)
    else:
        match = re.search(r"(?s)\bsolve\s*\(\)\s*\{", source)

    if not match:
        return source

    pos = match.end()
    code = "\n" + "\n".join(_schema_input_code(language, schema, "    ")) + "\n"
    return source[:pos] + code + source[pos:]


def _has_entrypoint(source: str, language: str) -> bool:
    if language == "Python":
        return bool(re.search(r"(?m)^\s*if\s+__name__\s*==\s*['\"]__main__['\"]", source))
    if language == "C++":
        return bool(re.search(r"(?m)\bint\s+main\s*\(", source))
    if language == "Java":
        return bool(re.search(r"(?m)public\s+static\s+void\s+main\s*\(", source))
    if language in {"JavaScript", "TypeScript"}:
        return bool(re.search(r"process\.stdout\.write|console\.log\s*\(", source))
    if language == "Go":
        return bool(re.search(r"(?m)\bfunc\s+main\s*\(", source))
    return bool(re.search(r"(?m)\bfn\s+main\s*\(", source))


def _ensure_language_imports(source: str, language: str) -> str:
    if language == "Python":
        return source if re.search(r"(?m)^\s*import\s+sys\b", source) else "import sys\n\n" + source

    if language == "C++":
        return source if "#include <bits/stdc++.h>" in source else "#include <bits/stdc++.h>\n" + source

    if language in {"JavaScript", "TypeScript"}:
        if "require('fs')" in source or 'require("fs")' in source:
            return source
        if language == "TypeScript":
            return "declare const require: (name: string) => any;\nconst fs: any = require('fs');\n\n" + source
        return "const fs = require('fs');\n\n" + source

    if language == "Go":
        return _ensure_go_imports(source)

    if language == "Rust":
        return source if "use std::io::Read;" in source else "use std::io::Read;\n" + source

    return source


def _append_user_io_entrypoint(source: str, language: str) -> str:
    if language == "Python":
        return source.rstrip() + "\n\nif __name__ == '__main__':\n    print(solve())\n"

    if language == "C++":
        is_void = bool(re.search(r"\bvoid\s+solve\s*\(\s*\)", source))
        if is_void:
            body = "    solve();"
            printer = ""
        else:
            body = "    auto __cm_result = solve();\n    __cm_print(__cm_result);"
            printer = (
                "\n\ntemplate <typename T> void __cm_print(const T& value) { cout << value; }\n"
                "template <typename T> void __cm_print(const vector<T>& value) {\n"
                "    for (size_t i = 0; i < value.size(); ++i) {\n"
                "        if (i) cout << ' ';\n"
                "        __cm_print(value[i]);\n"
                "    }\n"
                "}\n"
            )
        return (
            source.rstrip()
            + printer
            + "\nint main() {\n"
            + "    ios::sync_with_stdio(false);\n"
            + "    cin.tie(nullptr);\n"
            + body
            + "\n    return 0;\n}\n"
        )

    if language == "Java":
        # The original Solution class remains intact; Main is the JVM entrypoint.
        if "public class Main" in source:
            return source
        is_void = bool(re.search(r"\bvoid\s+solve\s*\(\s*\)", source))
        call = (
            "new Solution().solve();"
            if is_void
            else "Object __cm_result = new Solution().solve();\n        System.out.println(__cm_result);"
        )
        return (
            source.rstrip()
            + "\n\npublic class Main {\n"
            + "    public static void main(String[] args) {\n"
            + "        "
            + call.replace("\n", "\n        ")
            + "\n    }\n"
            + "}\n"
        )

    if language in {"JavaScript", "TypeScript"}:
        return source.rstrip() + "\n\nprocess.stdout.write(String(solve()));\n"

    if language == "Go":
        solve_signature = re.search(r"\bfunc\s+solve\(\)\s*([^{\n]*)\{", source)
        returns_value = bool(solve_signature and solve_signature.group(1).strip())
        if returns_value:
            body = "    __cm_result := solve()\n    fmt.Println(__cm_result)"
        else:
            body = "    solve()"
        return source.rstrip() + "\n\nfunc main() {\n" + body + "\n}\n"

    return source.rstrip() + '\n\nfn main() {\n    println!("{}", solve());\n}\n'


def _ensure_go_imports(source: str) -> str:
    required = ['"bufio"', '"fmt"', '"os"']
    if all(item in source for item in required):
        return source

    if "import (" in source:
        for item in required:
            if item not in source:
                source = source.replace("import (\n", f"import (\n    {item}\n", 1)
        return source

    return source.replace("package main\n", "package main\n\nimport (\n    \"bufio\"\n    \"fmt\"\n    \"os\"\n)\n", 1)


def ensure_user_io_starter_code(
    starter_code: Any = None,
    editor_schema: Any = None,
) -> dict[str, str]:
    """Preserve the problem's boilerplate while making input/output stdin/stdout based."""
    existing = starter_code if isinstance(starter_code, dict) else {}
    schema = normalize_editor_input_schema(editor_schema)

    result: dict[str, str] = {}
    for language in SUPPORTED_LANGUAGES:
        source = existing.get(language)
        if not isinstance(source, str) or not source.strip():
            result[language] = USER_IO_STARTERS[language]
            continue

        transformed, found = _replace_solve_signature(source, language)
        if not found:
            # Already a complete stdin/stdout program: keep all of it.
            result[language] = source
            continue

        transformed = _ensure_language_imports(transformed, language)
        transformed = _insert_after_solve_opening(transformed, language, schema)

        if not _has_entrypoint(transformed, language):
            transformed = _append_user_io_entrypoint(transformed, language)

        result[language] = transformed

    return result


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

    schema = _canonicalize_editor_schema(editor_schema)
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
            names = [item["name"] for item in schema_for_names if item["name"]]
        names = _safe_function_parameter_names(names)
        values = _argument_values(test_cases, len(names), schema)
        generated = _generated_function_starters(names, values)
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
    normalized["slug"] = normalize_text(problem.get("slug")).lower()
    normalized["title"] = normalize_text(problem.get("title"))
    normalized["description"] = strip_examples_from_description(problem.get("description"), problem.get("examples"))
    normalized["difficulty"] = normalize_difficulty(problem.get("difficulty"))
    normalized["topics"] = canonicalize_topics(problem.get("topics"))
    raw_constraints = problem.get("constraints")
    normalized["constraints"] = (
        [normalize_text(item) for item in raw_constraints if normalize_text(item)]
        if isinstance(raw_constraints, list)
        else extract_constraints(problem.get("description"))
    )
    metadata = dict(problem.get("package_metadata") or {})
    metadata["catalog_format_version"] = CATALOG_FORMAT_VERSION
    metadata["supported_languages"] = list(SUPPORTED_LANGUAGES)
    normalized["source"] = normalize_text(problem.get("source")) or "imported"
    normalized["execution_mode"] = infer_execution_mode(
        problem.get("execution_mode"),
        test_cases=problem.get("test_cases"),
        starter_code=problem.get("starter_code"),
        examples=problem.get("examples"),
    )
    schema = (
        editor_schema_from_metadata(metadata, problem.get("description"), problem.get("examples"))
        if normalized["execution_mode"] == "stdio"
        else function_editor_schema_from_problem(
            problem.get("starter_code"),
            problem.get("test_cases"),
            problem.get("examples"),
            problem.get("description"),
            explicit_schema=metadata.get("editor_input_schema"),
        )
    )
    schema = _canonicalize_editor_schema(schema)
    normalized["editor_input_schema"] = schema
    metadata["editor_input_schema"] = schema
    normalized["starter_code"] = ensure_starter_code(
        problem.get("starter_code"),
        normalized["execution_mode"],
        problem.get("test_cases"),
        problem.get("examples"),
        editor_schema=schema,
    )
    normalized["external_id"] = normalize_text(problem.get("external_id")) or None
    external_url = problem.get("external_url")
    normalized["external_url"] = external_url.strip() or None if isinstance(external_url, str) else None
    normalized["package_metadata"] = metadata
    return normalized

