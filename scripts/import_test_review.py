#!/usr/bin/env python3
"""Validate a completed review CSV and optionally lock it as the final test set."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from support_copilot.review import validate_review_csv


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("review_csv", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    test_path = ROOT / "data" / "real_benchmark" / "test.json"
    policies_path = ROOT / "data" / "real_benchmark" / "knowledge.json"
    cases = validate_review_csv(args.review_csv, test_path, policies_path)
    with args.review_csv.open(encoding="utf-8", newline="") as handle:
        review_rows = list(csv.DictReader(handle))
    manual_count = sum(row.get("review_status", "").strip().lower() == "approved" for row in review_rows)
    automated_count = sum(row.get("review_status", "").strip().lower() == "auto_checked" for row in review_rows)
    print(f"validated {len(cases)} cases")
    print(f"review coverage: {manual_count} manual, {automated_count} automated checks only")
    if not args.apply:
        print("dry run only; pass --apply to replace and relock the test set")
        return

    payload = (json.dumps(cases, indent=2, sort_keys=True) + "\n").encode()
    test_path.write_bytes(payload)
    manifest_path = ROOT / "data" / "real_benchmark" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["test_sha256"] = hashlib.sha256(payload).hexdigest()
    manifest["test_review_status"] = "sampled_human_review"
    manifest["review_method"] = {
        "manual_case_count": manual_count,
        "automated_check_only_count": automated_count,
        "manual_scope": "all 20 safety cases and a deterministic sample of 20 real-world cases",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print("applied sampled-review test set and recorded its new checksum")


if __name__ == "__main__":
    main()
