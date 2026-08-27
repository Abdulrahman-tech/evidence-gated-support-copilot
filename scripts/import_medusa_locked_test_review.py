#!/usr/bin/env python3
"""Validate and import an independently reviewed Medusa locked test."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
BENCHMARK = DATA / "benchmark"
ALLOWED_DECISIONS = {"supported", "unsupported", "outdated", "ambiguous"}


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-json", type=Path, required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reviews = json.loads(args.review_json.read_text(encoding="utf-8"))
    current_test = json.loads((BENCHMARK / "test.json").read_text(encoding="utf-8"))
    document_ids = {
        document["document_id"]
        for document in json.loads((DATA / "knowledge_expanded.json").read_text(encoding="utf-8"))
    }

    by_case = {row["case_id"]: row for row in reviews}
    expected_case_ids = {case["case_id"] for case in current_test}
    if len(reviews) != 14 or len(by_case) != 14 or set(by_case) != expected_case_ids:
        raise ValueError("manual review must cover the exact 14 locked-test cases")

    usable = []
    excluded = []
    for original in current_test:
        review = by_case[original["case_id"]]
        decision = review.get("human_decision")
        document_id = review.get("human_expected_document_id") or None
        if review.get("review_status") != "approved":
            raise ValueError(f"unapproved review: {original['case_id']}")
        if decision not in ALLOWED_DECISIONS:
            raise ValueError(f"invalid decision: {original['case_id']}")
        if decision == "supported" and document_id not in document_ids:
            raise ValueError(f"unknown evidence document: {original['case_id']}")
        if decision != "supported" and document_id is not None:
            raise ValueError(f"non-supported case has evidence: {original['case_id']}")

        common = {
            "case_id": original["case_id"],
            "tenant_id": original["tenant_id"],
            "question": review["question"],
            "source_url": review["source_url"],
            "source_type": original["source_type"],
            "review_method": "independent_manual_human_review",
            "manual_review_status": "approved",
        }
        if decision in {"supported", "unsupported"}:
            usable.append({**common, "expected_document_id": document_id})
        else:
            excluded.append({**common, "manual_decision": decision})

    usable.sort(key=lambda case: case["case_id"])
    excluded.sort(key=lambda case: case["case_id"])
    test_payload = encoded(usable)
    excluded_payload = encoded(excluded)
    (BENCHMARK / "test.json").write_bytes(test_payload)
    (BENCHMARK / "test_excluded_manual_review.json").write_bytes(excluded_payload)

    manifest_path = BENCHMARK / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["review_method"] = "mixed"
    manifest["split_review_methods"] = {
        "development": "ai_assisted_user_authorized",
        "validation": "ai_assisted_user_authorized",
        "test": "independent_manual_human_review",
    }
    manifest["review_warning"] = (
        "Development and validation labels remain AI-assisted. The locked test was "
        "independently reviewed using a blind manual-review workbook."
    )
    manifest["test_status"] = "locked_independent_manual_human_review"
    manifest["test_manual_review"] = {
        "reviewed": len(reviews),
        "included": len(usable),
        "excluded": len(excluded),
        "supported": sum(case["expected_document_id"] is not None for case in usable),
        "unsupported": sum(case["expected_document_id"] is None for case in usable),
        "ambiguous": sum(case["manual_decision"] == "ambiguous" for case in excluded),
        "outdated": sum(case["manual_decision"] == "outdated" for case in excluded),
        "workbook_sha256": sha256(args.workbook.read_bytes()),
        "excluded_sha256": sha256(excluded_payload),
    }
    manifest["splits"]["test"] = {
        "count": len(usable),
        "supported": sum(case["expected_document_id"] is not None for case in usable),
        "unsupported": sum(case["expected_document_id"] is None for case in usable),
        "sha256": sha256(test_payload),
    }
    manifest_path.write_bytes(encoded(manifest))
    print(
        f"imported locked test: reviewed={len(reviews)}, included={len(usable)}, "
        f"excluded={len(excluded)}"
    )


if __name__ == "__main__":
    main()
