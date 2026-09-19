from backend.models import Problem

PROBLEMS = [
    {
        "slug": "longest-window-under-budget",
        "title": "Longest Window Under Budget",
        "difficulty": "Medium",
        "topics": ["Arrays & Strings", "Two Pointers", "Sliding Window"],
        "description": "Given a list of positive integers nums and an integer budget, find the maximum length of a contiguous subarray whose sum is at most budget.",
        "constraints": ["1 <= len(nums) <= 100000", "1 <= nums[i] <= 1000", "1 <= budget <= 1000000000"],
        "examples": [
            {"input": "nums = [2, 1, 3, 2, 1], budget = 6", "output": "3", "explanation": "The window [1, 3, 2] has sum 6."},
            {"input": "nums = [5, 1, 1, 1], budget = 3", "output": "3", "explanation": "The window [1, 1, 1] has sum 3."},
        ],
        "test_cases": [
            {"args": [[[2, 1, 3, 2, 1], 6]], "expected": 3},
            {"args": [[[5, 1, 1, 1], 3]], "expected": 3},
            {"args": [[[5, 5, 5], 4]], "expected": 0},
            {"args": [[[1, 1, 1, 1, 1], 3]], "expected": 3},
        ],
        "starter_code": {
            "Python": "def solve(nums, budget):\n    # Return the maximum valid window length.\n    pass\n",
            "C++": "#include <bits/stdc++.h>\nusing namespace std;\n\nint solve(vector<int>& nums, long long budget) {\n    // Return the maximum valid window length.\n    return 0;\n}\n",
            "Java": "class Solution {\n    public int solve(int[] nums, long budget) {\n        // Return the maximum valid window length.\n        return 0;\n    }\n}\n",
        },
    },
    {
        "slug": "first-repeated-value",
        "title": "First Repeated Value",
        "difficulty": "Easy",
        "topics": ["Arrays & Strings", "Hashing & Hash Maps"],
        "description": "Given an integer array nums, return the first value that appears for the second time when scanning from left to right. Return -1 when every value is unique.",
        "constraints": ["1 <= len(nums) <= 100000", "-1000000000 <= nums[i] <= 1000000000"],
        "examples": [
            {"input": "nums = [4, 7, 2, 7, 9]", "output": "7", "explanation": "7 is the first value encountered for the second time."},
            {"input": "nums = [1, 2, 3]", "output": "-1", "explanation": "No value occurs twice."},
        ],
        "test_cases": [
            {"args": [[4, 7, 2, 7, 9]], "expected": 7},
            {"args": [[1, 2, 3]], "expected": -1},
            {"args": [[5, 5]], "expected": 5},
            {"args": [[9, 2, 9, 2]], "expected": 9},
        ],
        "starter_code": {
            "Python": "def solve(nums):\n    # Return the first repeated value, or -1.\n    pass\n",
            "C++": "#include <bits/stdc++.h>\nusing namespace std;\n\nint solve(vector<int>& nums) {\n    // Return the first repeated value, or -1.\n    return -1;\n}\n",
            "Java": "class Solution {\n    public int solve(int[] nums) {\n        // Return the first repeated value, or -1.\n        return -1;\n    }\n}\n",
        },
    },
    {
        "slug": "minimum-platform-groups",
        "title": "Minimum Platform Groups",
        "difficulty": "Medium",
        "topics": ["Greedy Algorithms", "Arrays & Strings"],
        "description": "You are given arrival and departure times for trains at a station. Find the minimum number of platforms required so that no train waits.",
        "constraints": ["1 <= n <= 100000", "Arrival and departure times are non-negative integers.", "For each train, arrival <= departure."],
        "examples": [
            {"input": "arrivals = [100, 200, 300], departures = [150, 250, 350]", "output": "1", "explanation": "The trains do not overlap."},
            {"input": "arrivals = [100, 120, 140], departures = [200, 220, 160]", "output": "3", "explanation": "All three trains overlap around time 140."},
        ],
        "test_cases": [
            {"args": [[[100, 200, 300], [150, 250, 350]]], "expected": 1},
            {"args": [[[100, 120, 140], [200, 220, 160]]], "expected": 3},
            {"args": [[[100], [100]]], "expected": 1},
            {"args": [[[100, 110], [120, 130]]], "expected": 1},
        ],
        "starter_code": {
            "Python": "def solve(arrivals, departures):\n    # Return the minimum number of platforms.\n    pass\n",
            "C++": "#include <bits/stdc++.h>\nusing namespace std;\n\nint solve(vector<int>& arrivals, vector<int>& departures) {\n    // Return the minimum number of platforms.\n    return 0;\n}\n",
            "Java": "class Solution {\n    public int solve(int[] arrivals, int[] departures) {\n        // Return the minimum number of platforms.\n        return 0;\n    }\n}\n",
        },
    },
    {
        "slug": "graph-reachability-count",
        "title": "Reachable Node Count",
        "difficulty": "Easy",
        "topics": ["Graphs (BFS/DFS)"],
        "description": "Given an undirected graph with n nodes and an edge list, return how many nodes are reachable from a given start node, including the start node itself.",
        "constraints": ["1 <= n <= 100000", "0 <= len(edges) <= 200000", "0 <= start < n"],
        "examples": [
            {"input": "n = 5, edges = [[0,1],[1,2],[3,4]], start = 0", "output": "3", "explanation": "Nodes 0, 1, and 2 are reachable."},
            {"input": "n = 4, edges = [], start = 2", "output": "1", "explanation": "Only the start node is reachable."},
        ],
        "test_cases": [
            {"args": [[5, [[0,1],[1,2],[3,4]], 0]], "expected": 3},
            {"args": [[4, [], 2]], "expected": 1},
            {"args": [[6, [[0,1],[1,2],[2,3],[4,5]], 4]], "expected": 2},
            {"args": [[3, [[0,1],[1,2]], 2]], "expected": 3},
        ],
        "starter_code": {
            "Python": "def solve(n, edges, start):\n    # Return the number of reachable nodes.\n    pass\n",
            "C++": "#include <bits/stdc++.h>\nusing namespace std;\n\nint solve(int n, vector<vector<int>>& edges, int start) {\n    // Return the number of reachable nodes.\n    return 0;\n}\n",
            "Java": "class Solution {\n    public int solve(int n, int[][] edges, int start) {\n        // Return the number of reachable nodes.\n        return 0;\n    }\n}\n",
        },
    },
    {
        "slug": "min-cost-stair-climb",
        "title": "Minimum Cost Stair Climb",
        "difficulty": "Medium",
        "topics": ["Dynamic Programming", "Arrays & Strings"],
        "description": "Each step has a non-negative cost. From step i, you may move one or two steps. Return the minimum total cost required to reach beyond the last step.",
        "constraints": ["2 <= len(cost) <= 100000", "0 <= cost[i] <= 10000"],
        "examples": [
            {"input": "cost = [10, 15, 20]", "output": "15", "explanation": "Take the first and third positions via a two-step move."},
            {"input": "cost = [1, 100, 1, 1, 1, 100, 1, 1, 100, 1]", "output": "6", "explanation": "Choose the lower-cost path through the staircase."},
        ],
        "test_cases": [
            {"args": [[10, 15, 20]], "expected": 15},
            {"args": [[1, 100, 1, 1, 1, 100, 1, 1, 100, 1]], "expected": 6},
            {"args": [[1, 2]], "expected": 1},
            {"args": [[5, 5, 5, 5]], "expected": 10},
        ],
        "starter_code": {
            "Python": "def solve(cost):\n    # Return the minimum cost to reach the top.\n    pass\n",
            "C++": "#include <bits/stdc++.h>\nusing namespace std;\n\nint solve(vector<int>& cost) {\n    // Return the minimum cost to reach the top.\n    return 0;\n}\n",
            "Java": "class Solution {\n    public int solve(int[] cost) {\n        // Return the minimum cost to reach the top.\n        return 0;\n    }\n}\n",
        },
    },
]

def seed_problems(db):
    for item in PROBLEMS:
        existing = db.query(Problem).filter(Problem.slug == item["slug"]).first()
        if existing is None:
            db.add(Problem(**item))
        else:
            # Backfill execution tests for problems created by an earlier schema version.
            if not existing.test_cases:
                existing.test_cases = item.get("test_cases", [])
    db.commit()
