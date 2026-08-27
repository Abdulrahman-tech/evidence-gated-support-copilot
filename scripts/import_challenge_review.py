#!/usr/bin/env python3
"""Validate approved challenge adjudication and create a separate judged split."""

import argparse
import hashlib
import json
from pathlib import Path

from support_copilot.challenge_review import import_challenge_review


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "real_benchmark"


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--review",
        type=Path,
        default=ROOT / "review" / "challenge_unsupported_review.csv",
    )
    parser.add_argument(
        "--review-method",
        choices=("case_by_case", "blanket_approval"),
        default="case_by_case",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    judged, counts = import_challenge_review(
        args.review,
        BENCHMARK / "challenge.json",
        BENCHMARK / "challenge_knowledge.json",
    )
    print(f"validated challenge decisions: {counts}")
    if not args.apply:
        print("validation only; pass --apply to write challenge_judged.json")
        return

    judged_bytes = encoded(judged)
    output = BENCHMARK / "challenge_judged.json"
    output.write_bytes(judged_bytes)
    manifest_path = BENCHMARK / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["challenge_review_status"] = (
        "human_adjudicated"
        if args.review_method == "case_by_case"
        else "user_blanket_approved"
    )
    manifest["challenge_review_method"] = args.review_method
    manifest["challenge_judged_case_count"] = len(judged)
    manifest["challenge_ambiguous_excluded_count"] = counts["ambiguous"]
    manifest["challenge_judged_sha256"] = hashlib.sha256(judged_bytes).hexdigest()
    manifest_path.write_bytes(encoded(manifest))
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
