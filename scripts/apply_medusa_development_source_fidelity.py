#!/usr/bin/env python3
"""Apply a complete source-fidelity audit to the Medusa development split only."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
BENCHMARK = DATA / "benchmark"
ALLOWED_DECISIONS = {"supported", "unsupported", "outdated"}


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--audit-id", required=True)
    args = parser.parse_args()

    development_path = BENCHMARK / "development.json"
    validation_path = BENCHMARK / "validation.json"
    test_path = BENCHMARK / "test.json"
    manifest_path = BENCHMARK / "manifest.json"
    validation_before = validation_path.read_bytes()
    test_before = test_path.read_bytes()
    development = json.loads(development_path.read_text(encoding="utf-8"))
    audit_bytes = args.audit.read_bytes()
    audit = json.loads(audit_bytes)
    audit_by_case = {row.get("case_id"): row for row in audit}
    development_by_case = {row["case_id"]: row for row in development}
    if len(audit_by_case) != len(audit) or set(audit_by_case) != set(development_by_case):
        raise ValueError("source-fidelity audit must cover every development case once")

    protected_ids = {
        case["case_id"]
        for path in (validation_path, test_path)
        for case in json.loads(path.read_text(encoding="utf-8"))
    }
    if set(audit_by_case) & protected_ids:
        raise ValueError("source-fidelity audit overlaps a protected split")
    document_ids = {
        row["document_id"]
        for row in json.loads((DATA / "knowledge_expanded.json").read_text())
    }

    revised = []
    excluded = []
    counts: collections.Counter[str] = collections.Counter()
    review_methods = set()
    for case in development:
        row = audit_by_case[case["case_id"]]
        decision = row.get("reviewer_decision")
        expected = row.get("expected_document_id") or None
        reviewed_question = str(row.get("reviewed_question") or "").strip()
        if row.get("review_status") != "approved":
            raise ValueError(f"unapproved audit case: {case['case_id']}")
        if decision not in ALLOWED_DECISIONS:
            raise ValueError(f"invalid audit decision: {case['case_id']}")
        if not row.get("source_hash_matches"):
            raise ValueError(f"source hash mismatch: {case['case_id']}")
        if row.get("source_url") != case["source_url"]:
            raise ValueError(f"source URL drift: {case['case_id']}")
        if row.get("current_expected_document_id") != case["expected_document_id"]:
            raise ValueError(f"starting label drift: {case['case_id']}")
        if not reviewed_question or len(reviewed_question) > 8_000:
            raise ValueError(f"invalid reviewed question: {case['case_id']}")
        if decision == "supported" and expected not in document_ids:
            raise ValueError(f"unknown evidence document: {case['case_id']}")
        if decision != "supported" and expected is not None:
            raise ValueError(f"non-supported case has evidence: {case['case_id']}")
        review_method = str(row.get("review_method") or "").strip()
        if not review_method:
            raise ValueError(f"missing review method: {case['case_id']}")
        review_methods.add(review_method)
        counts[decision] += 1
        updated = {
            **case,
            "question": reviewed_question,
            "expected_document_id": expected,
            "review_method": review_method,
            "review_batch": args.audit_id,
            "review_notes": row.get("review_notes", ""),
            "source_question_sha256": row["source_question_sha256"],
            "source_word_count": row["source_word_count"],
        }
        if decision == "outdated":
            excluded.append(
                {
                    "case_id": case["case_id"],
                    "decision": decision,
                    "original_question": case["question"],
                    "reviewed_question": reviewed_question,
                    "review_notes": row.get("review_notes", ""),
                    "source_url": case["source_url"],
                }
            )
        else:
            revised.append(updated)
    if len(review_methods) != 1:
        raise ValueError("source-fidelity audit must use one declared review method")

    revised.sort(key=lambda row: row["case_id"])
    excluded.sort(key=lambda row: row["case_id"])
    revised_bytes = encoded(revised)
    excluded_bytes = encoded(excluded)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["development_source_fidelity_audit"] = {
        "audit_id": args.audit_id,
        "audit_sha256": digest(audit_bytes),
        "review_method": next(iter(review_methods)),
        "reviewed": len(audit),
        "included": len(revised),
        "excluded": len(excluded),
        "supported": counts["supported"],
        "unsupported": counts["unsupported"],
        "outdated": counts["outdated"],
        "source_hash_matches": sum(row["source_hash_matches"] for row in audit),
        "excluded_sha256": digest(excluded_bytes),
    }
    manifest["split_review_methods"]["development"] = next(iter(review_methods))
    manifest["review_warning"] = (
        "Development uses an AI-assisted, user-authorized full-source audit. "
        "Validation labels remain AI-assisted. The locked test remains independently reviewed."
    )
    manifest["splits"]["development"] = {
        "count": len(revised),
        "supported": counts["supported"],
        "unsupported": counts["unsupported"],
        "sha256": digest(revised_bytes),
    }
    manifest_bytes = encoded(manifest)

    atomic_write(development_path, revised_bytes)
    atomic_write(args.audit.parent / "excluded.json", excluded_bytes)
    atomic_write(manifest_path, manifest_bytes)
    if validation_path.read_bytes() != validation_before or test_path.read_bytes() != test_before:
        raise RuntimeError("protected benchmark split changed")
    print(
        f"applied source fidelity: reviewed={len(audit)} included={len(revised)} "
        f"supported={counts['supported']} unsupported={counts['unsupported']} "
        f"outdated={counts['outdated']}"
    )


if __name__ == "__main__":
    main()
