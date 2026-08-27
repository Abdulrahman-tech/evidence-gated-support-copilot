#!/usr/bin/env python3
"""Export proposed unsupported challenge cases for fast human adjudication."""

from pathlib import Path

from support_copilot.challenge_review import export_challenge_review


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "real_benchmark"


def main() -> None:
    output = ROOT / "review" / "challenge_unsupported_review.csv"
    output.parent.mkdir(exist_ok=True)
    export_challenge_review(
        BENCHMARK / "challenge.json",
        BENCHMARK / "challenge_knowledge.json",
        output,
    )
    print(f"exported 100 proposed unsupported cases to {output}")


if __name__ == "__main__":
    main()
