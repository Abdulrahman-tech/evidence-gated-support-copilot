#!/usr/bin/env python3
"""Export the locked test split to a human-review CSV."""

from pathlib import Path

from support_copilot.review import export_review_csv


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    output = ROOT / "review" / "test_review.csv"
    output.parent.mkdir(exist_ok=True)
    export_review_csv(
        ROOT / "data" / "real_benchmark" / "test.json",
        ROOT / "data" / "real_benchmark" / "knowledge.json",
        output,
        fast_review=True,
    )
    print(f"exported {output}")


if __name__ == "__main__":
    main()
