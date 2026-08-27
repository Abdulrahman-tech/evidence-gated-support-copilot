#!/usr/bin/env python3
"""Validate and import a reviewed Medusa development-only manual batch."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
BENCHMARK = DATA / "benchmark"
REVIEW_METHOD = "user_reviewed_codex_applied"
ALLOWED_DECISIONS = {"supported", "unsupported", "ambiguous", "outdated"}


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-json", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--review-json", type=Path, required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    batch_path = args.batch_json
    batch_manifest_path = batch_path.with_name(
        batch_path.name.removesuffix(".json") + "_manifest.json"
    )
    excluded_path = batch_path.with_name(
        batch_path.name.removesuffix(".json") + "_excluded.json"
    )
    benchmark_manifest_path = BENCHMARK / "manifest.json"
    development_path = BENCHMARK / "development.json"
    validation_path = BENCHMARK / "validation.json"
    test_path = BENCHMARK / "test.json"

    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    reviews = json.loads(args.review_json.read_text(encoding="utf-8"))
    documents = json.loads((DATA / "knowledge_expanded.json").read_text(encoding="utf-8"))
    assignments = json.loads(
        (DATA / "candidate_pool" / "assignments.json").read_text(encoding="utf-8")
    )
    document_ids = {document["document_id"] for document in documents}
    roles = {item["case_id"]: item["role"] for item in assignments}
    review_by_case = {row["case_id"]: row for row in reviews}
    batch_ids = {item["case_id"] for item in batch}

    if len(batch) != 30 or len(batch_ids) != 30:
        raise ValueError("manual batch must contain 30 unique cases")
    if len(reviews) != 30 or len(review_by_case) != 30 or set(review_by_case) != batch_ids:
        raise ValueError("review must cover the exact 30 manual-batch cases")
    if any(roles.get(case_id) != "development" for case_id in batch_ids):
        raise ValueError("manual batch contains a non-development case")

    reviewed_batch = []
    imported_cases = []
    excluded_cases = []
    for original in batch:
        review = review_by_case[original["case_id"]]
        decision = str(review.get("reviewer_decision") or "").strip().lower()
        document_id = str(review.get("expected_document_id") or "").strip() or None
        status = str(review.get("review_status") or "").strip().lower()
        if status != "approved":
            raise ValueError(f"unapproved review: {original['case_id']}")
        if decision not in ALLOWED_DECISIONS:
            raise ValueError(f"invalid decision: {original['case_id']}")
        if decision == "supported" and document_id not in document_ids:
            raise ValueError(f"unknown evidence document: {original['case_id']}")
        if decision != "supported" and document_id is not None:
            raise ValueError(f"non-supported case has evidence: {original['case_id']}")

        reviewed_question = str(
            review.get("reviewed_question") or original["reviewed_question"]
        ).strip()
        reviewed_batch.append(
            {
                **original,
                "reviewed_question": reviewed_question,
                "reviewer_decision": decision,
                "expected_document_id": document_id or "",
                "review_notes": str(review.get("review_notes") or "").strip(),
                "review_status": "approved",
                "review_method": REVIEW_METHOD,
            }
        )
        common = {
            "case_id": original["case_id"],
            "tenant_id": "medusa",
            "question": reviewed_question,
            "source_url": original["source_url"],
            "source_type": "github_issue_manual_review",
            "review_method": REVIEW_METHOD,
            "review_batch": args.batch_id,
            "review_notes": str(review.get("review_notes") or "").strip(),
        }
        if decision in {"supported", "unsupported"}:
            imported_cases.append({**common, "expected_document_id": document_id})
        else:
            excluded_cases.append({**common, "manual_decision": decision})

    validation_before = validation_path.read_bytes()
    test_before = test_path.read_bytes()
    development = json.loads(development_path.read_text(encoding="utf-8"))
    protected_ids = {
        case["case_id"]
        for path in (validation_path, test_path)
        for case in json.loads(path.read_text(encoding="utf-8"))
    }
    if batch_ids & protected_ids:
        raise ValueError("manual batch overlaps validation or locked test")

    development = [case for case in development if case["case_id"] not in batch_ids]
    development.extend(imported_cases)
    development.sort(key=lambda case: case["case_id"])
    if len({case["case_id"] for case in development}) != len(development):
        raise ValueError("duplicate development case ID after import")

    reviewed_batch.sort(key=lambda item: item["case_id"])
    excluded_cases.sort(key=lambda item: item["case_id"])
    reviewed_payload = encoded(reviewed_batch)
    excluded_payload = encoded(excluded_cases)
    development_payload = encoded(development)
    batch_path.write_bytes(reviewed_payload)
    excluded_path.write_bytes(excluded_payload)
    development_path.write_bytes(development_payload)

    decision_counts = dict(
        sorted(collections.Counter(item["reviewer_decision"] for item in reviewed_batch).items())
    )
    workbook_hash = sha256(args.workbook.read_bytes())
    batch_manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
    batch_manifest.setdefault("selection_sha256", batch_manifest["sha256"])
    batch_manifest.update(
        {
            "labels_included": True,
            "review_method": REVIEW_METHOD,
            "review_status": "approved",
            "reviewer_decision_counts": decision_counts,
            "usable_count": len(imported_cases),
            "excluded_count": len(excluded_cases),
            "excluded_sha256": sha256(excluded_payload),
            "workbook_sha256": workbook_hash,
            "sha256": sha256(reviewed_payload),
        }
    )
    batch_manifest_path.write_bytes(encoded(batch_manifest))

    benchmark_manifest = json.loads(benchmark_manifest_path.read_text(encoding="utf-8"))
    benchmark_manifest["split_review_methods"]["development"] = "mixed"
    review_record = {
        "batch_id": args.batch_id,
        "review_method": REVIEW_METHOD,
        "reviewed": len(reviewed_batch),
        "included": len(imported_cases),
        "excluded": len(excluded_cases),
        "supported": decision_counts.get("supported", 0),
        "unsupported": decision_counts.get("unsupported", 0),
        "ambiguous": decision_counts.get("ambiguous", 0),
        "outdated": decision_counts.get("outdated", 0),
        "workbook_sha256": workbook_hash,
        "reviewed_batch_sha256": sha256(reviewed_payload),
        "excluded_sha256": sha256(excluded_payload),
    }
    manual_reviews = benchmark_manifest.get("development_manual_reviews")
    if manual_reviews is None:
        previous = benchmark_manifest.get("development_manual_review")
        manual_reviews = [previous] if previous else []
    manual_reviews = [
        review for review in manual_reviews if review["batch_id"] != args.batch_id
    ]
    manual_reviews.append(review_record)
    benchmark_manifest["development_manual_reviews"] = sorted(
        manual_reviews, key=lambda review: review["batch_id"]
    )
    benchmark_manifest.pop("development_manual_review", None)
    benchmark_manifest["review_warning"] = (
        "Development combines AI-assisted labels with user-reviewed manual batches. "
        "Validation labels remain AI-assisted. The locked test was independently reviewed."
    )
    benchmark_manifest["splits"]["development"] = {
        "count": len(development),
        "supported": sum(case["expected_document_id"] is not None for case in development),
        "unsupported": sum(case["expected_document_id"] is None for case in development),
        "sha256": sha256(development_payload),
    }
    benchmark_manifest_path.write_bytes(encoded(benchmark_manifest))

    if validation_path.read_bytes() != validation_before or test_path.read_bytes() != test_before:
        raise RuntimeError("protected benchmark split changed during development import")
    print(
        f"imported development manual batch: included={len(imported_cases)}, "
        f"excluded={len(excluded_cases)}, "
        f"supported={decision_counts.get('supported', 0)}, "
        f"unsupported={decision_counts.get('unsupported', 0)}"
    )


if __name__ == "__main__":
    main()
