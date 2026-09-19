# Bulk Problem Catalog Import

CodeMentor can import a large problem catalog from a JSON file. Use this for content you are authorized to store and redistribute.

## JSON shape

```json
{
  "problems": [
    {
      "slug": "example-problem",
      "title": "Example Problem",
      "difficulty": "Medium",
      "topics": ["Arrays & Strings"],
      "description": "Problem statement...",
      "constraints": ["1 <= n <= 100000"],
      "examples": [
        {"input": "...", "output": "...", "explanation": "..."}
      ],
      "test_cases": [
        {"args": [[1, 2, 3]], "expected": 3}
      ],
      "starter_code": {
        "Python": "def solve(nums):\n    pass\n"
      },
      "source": "licensed-provider",
      "external_id": "123",
      "external_url": "https://example.com/problems/example-problem"
    }
  ]
}
```

`test_cases` may be omitted for problems that are displayed as external/read-only content. Problems intended for CodeMentor's local execution engine should include the execution contract used by `backend/execution.py`.

## Import

From the project root:

```bash
python -m backend.import_problems path/to/catalog.json
```

The importer upserts by slug and, when supplied, by the `(source, external_id)` pair.

## LeetCode content

Do not populate this file by crawling, scraping, or spidering LeetCode. LeetCode's Terms prohibit those activities and state that its questions and related materials are protected content. Use an authorized/licensed export or integration instead.
