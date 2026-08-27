#!/usr/bin/env python3
"""Apply an approved label audit to Medusa development cases only."""

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
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--audit-id", required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    development_path = BENCHMARK / "development.json"
    validation_path = BENCHMARK / "validation.json"
    test_path = BENCHMARK / "test.json"
    manifest_path = BENCHMARK / "manifest.json"

    audit_bytes = args.audit_json.read_bytes()
    audit = json.loads(audit_bytes)
    document_ids = {
        document["document_id"]
        for document in json.loads((DATA / "knowledge_expanded.json").read_text())
    }
    audit_by_case = {row["case_id"]: row for row in audit}
    if not audit or len(audit_by_case) != len(audit):
        raise ValueError("audit must contain unique cases")

    for case_id, row in audit_by_case.items():
        decision = str(row.get("reviewer_decision") or "").strip().lower()
        document_id = str(row.get("expected_document_id") or "").strip() or None
        status = str(row.get("review_status") or "").strip().lower()
        if status != "approved":
            raise ValueError(f"unapproved audit row: {case_id}")
        if decision not in ALLOWED_DECISIONS:
            raise ValueError(f"invalid audit decision: {case_id}")
        if decision == "supported" and document_id not in document_ids:
            raise ValueError(f"unknown evidence document: {case_id}")
        if decision != "supported" and document_id is not None:
            raise ValueError(f"non-supported case has evidence: {case_id}")

    validation_before = validation_path.read_bytes()
    test_before = test_path.read_bytes()
    development = json.loads(development_path.read_text())
    development_by_case = {case["case_id"]: case for case in development}
    protected_ids = {
        case["case_id"]
        for path in (validation_path, test_path)
        for case in json.loads(path.read_text())
    }
    if set(audit_by_case) & protected_ids:
        raise ValueError("label audit overlaps validation or locked test")
    missing = sorted(set(audit_by_case) - set(development_by_case))
    if missing:
        raise ValueError(f"audit cases missing from development: {missing}")

    revised = []
    excluded = []
    for case in development:
        row = audit_by_case.get(case["case_id"])
        if row is None:
            revised.append(case)
            continue
        decision = row["reviewer_decision"]
        document_id = row["expected_document_id"] or None
        reviewed = {
            **case,
            "expected_document_id": document_id,
            "review_method": REVIEW_METHOD,
            "review_batch": args.audit_id,
        }
        if decision in {"supported", "unsupported"}:
            revised.append(reviewed)
        else:
            excluded.append(
                {
                    "case_id": case["case_id"],
                    "decision": decision,
                    "question": case["question"],
                    "source_url": case["source_url"],
                }
            )

    revised.sort(key=lambda case: case["case_id"])
    revised_payload = encoded(revised)
    development_path.write_bytes(revised_payload)

    manifest = json.loads(manifest_path.read_text())
    counts = collections.Counter(row["reviewer_decision"] for row in audit)
    audit_record = {
        "audit_id": args.audit_id,
        "review_method": REVIEW_METHOD,
        "reviewed": len(audit),
        "included": len(audit) - len(excluded),
        "excluded": len(excluded),
        "supported": counts["supported"],
        "unsupported": counts["unsupported"],
        "ambiguous": counts["ambiguous"],
        "outdated": counts["outdated"],
        "audit_sha256": sha256(audit_bytes),
        "workbook_sha256": sha256(args.workbook.read_bytes()),
        "excluded_cases": excluded,
    }
    audits = [
        record
        for record in manifest.get("development_label_audits", [])
        if record["audit_id"] != args.audit_id
    ]
    audits.append(audit_record)
    manifest["development_label_audits"] = sorted(
        audits, key=lambda record: record["audit_id"]
    )
    manifest["splits"]["development"] = {
        "count": len(revised),
        "supported": sum(case["expected_document_id"] is not None for case in revised),
        "unsupported": sum(case["expected_document_id"] is None for case in revised),
        "sha256": sha256(revised_payload),
    }
    manifest_path.write_bytes(encoded(manifest))

    if validation_path.read_bytes() != validation_before or test_path.read_bytes() != test_before:
        raise RuntimeError("protected benchmark split changed during development audit")
    print(
        f"applied development label audit: reviewed={len(audit)}, "
        f"included={len(audit) - len(excluded)}, excluded={len(excluded)}, "
        f"supported={counts['supported']}, unsupported={counts['unsupported']}"
    )


if __name__ == "__main__":
    main()
