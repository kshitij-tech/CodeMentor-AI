from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any, Iterable

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}

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


def duplicate_fingerprint(problem: dict[str, Any]) -> str:
    source = normalize_text(problem.get("source")).lower()
    external_id = normalize_text(problem.get("external_id")).lower()
    if source and external_id:
        raw = f"external:{source}:{external_id}"
    else:
        title = normalize_text(problem.get("title")).lower()
        description = normalize_text(problem.get("description")).lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", f"{title} {description}").strip()
        raw = f"content:{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def audit_problems(problems: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(problems)
    issue_counts: Counter[str] = Counter()
    fingerprint_map: dict[str, list[str]] = {}

    clean = 0
    for problem in items:
        flags = quality_flags(problem)
        issue_counts.update(flags)

        if not flags:
            clean += 1

        fingerprint = duplicate_fingerprint(problem)
        fingerprint_map.setdefault(fingerprint, []).append(
            normalize_text(problem.get("slug")) or normalize_text(problem.get("title"))
        )

    duplicates = {
        fingerprint: slugs
        for fingerprint, slugs in fingerprint_map.items()
        if len(slugs) > 1
    }

    if duplicates:
        issue_counts["duplicates"] = len(duplicates)

    return {
        "total": len(items),
        "clean": clean,
        "issues": dict(sorted(issue_counts.items())),
        "duplicates": duplicates,
    }


def normalize_problem_record(problem: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(problem)

    normalized["title"] = normalize_text(problem.get("title"))
    normalized["description"] = normalize_text(problem.get("description"))
    normalized["difficulty"] = normalize_difficulty(problem.get("difficulty"))
    normalized["topics"] = canonicalize_topics(problem.get("topics"))
    normalized["source"] = normalize_text(problem.get("source")) or "imported"

    external_id = problem.get("external_id")
    normalized["external_id"] = normalize_text(external_id) or None

    if isinstance(problem.get("external_url"), str):
        normalized["external_url"] = problem["external_url"].strip() or None

    return normalized
