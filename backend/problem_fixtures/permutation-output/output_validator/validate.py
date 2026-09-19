from __future__ import annotations

import sys
from pathlib import Path


def reject(feedback_dir: str, message: str) -> None:
    Path(feedback_dir, "teammessage.txt").write_text(message, encoding="utf-8")
    raise SystemExit(43)


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(2)

    input_path, answer_path, feedback_dir, *args = sys.argv[1:]
    input_text = Path(input_path).read_text(encoding="utf-8")
    team_output = sys.stdin.read()

    tokens = input_text.split()
    if not tokens:
        raise SystemExit(2)

    n = int(tokens[0])
    expected_values = [int(value) for value in tokens[1:]]
    output_values_text = team_output.split()

    if "strict" in args and len(output_values_text) > n:
        reject(feedback_dir, "Output contains more tokens than the required count.")

    try:
        output_values = [int(value) for value in output_values_text]
    except ValueError:
        reject(feedback_dir, "Output must contain integers only.")

    if len(output_values) != n:
        reject(feedback_dir, f"Expected exactly {n} integers, got {len(output_values)}.")

    if sorted(output_values) != sorted(expected_values):
        reject(feedback_dir, "Output is not a permutation of the input values.")

    raise SystemExit(42)


if __name__ == "__main__":
    main()
