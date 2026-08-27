#!/usr/bin/env python3
"""Apply approved discussion adjudication and build deterministic benchmark splits."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
OUTPUT = DATA / "benchmark"
SEED = "medusa-discussions-v1"


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def ranked(cases: list[dict]) -> list[dict]:
    return sorted(
        cases,
        key=lambda case: hashlib.sha256(
            f"{SEED}:{case['case_id']}".encode()
        ).hexdigest(),
    )


def main() -> None:
    manifest_path = OUTPUT / "manifest.json"
    if manifest_path.exists():
        existing_manifest = json.loads(manifest_path.read_text())
        if existing_manifest.get("test_status") == "locked_independent_manual_human_review":
            raise RuntimeError(
                "refusing to overwrite the independently reviewed locked test; "
                "preserve it or import a new completed manual review"
            )
    candidates = json.loads((DATA / "discussion_candidates.json").read_text())
    decisions = json.loads((DATA / "discussion_adjudication.json").read_text())
    documents = json.loads((DATA / "knowledge_expanded.json").read_text())
    document_ids = {document["document_id"] for document in documents}
    by_case = {decision["case_id"]: decision for decision in decisions}
    if len(candidates) != 100 or len(by_case) != len(candidates):
        raise ValueError("adjudication must cover all 100 unique candidates")

    reviewed = []
    benchmark = []
    for candidate in candidates:
        decision = by_case[candidate["case_id"]]
        label = decision["reviewer_decision"]
        expected = decision["expected_document_id"] or None
        if label == "supported" and expected not in document_ids:
            raise ValueError(f"unknown evidence document for {candidate['case_id']}")
        if label != "supported" and expected is not None:
            raise ValueError(f"non-supported case has evidence: {candidate['case_id']}")
        reviewed.append({**candidate, **decision})
        if label in {"supported", "unsupported"}:
            benchmark.append(
                {
                    "case_id": candidate["case_id"],
                    "tenant_id": "medusa",
                    "question": decision.get("reviewed_question", candidate["question"]),
                    "expected_document_id": expected,
                    "source_url": candidate["source_url"],
                    "source_type": "github_discussion_answered_q_and_a",
                    "review_method": decision["review_method"],
                }
            )

    supported = ranked([case for case in benchmark if case["expected_document_id"]])
    unsupported = ranked([case for case in benchmark if not case["expected_document_id"]])
    if (len(supported), len(unsupported)) != (30, 40):
        raise ValueError("expected 30 supported and 40 unsupported approved cases")

    splits = {
        "development": supported[:18] + unsupported[:24],
        "validation": supported[18:24] + unsupported[24:32],
        "test": supported[24:] + unsupported[32:],
    }
    for cases in splits.values():
        cases.sort(key=lambda case: case["case_id"])
    source_sets = [{case["source_url"] for case in cases} for cases in splits.values()]
    if any(source_sets[i] & source_sets[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("source leakage detected between benchmark splits")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    reviewed_payload = encoded(reviewed)
    (DATA / "discussion_candidates_reviewed.json").write_bytes(reviewed_payload)
    manifest = {
        "tenant_id": "medusa",
        "seed": SEED,
        "review_method": "ai_assisted_user_authorized",
        "review_warning": (
            "Labels were produced by AI-assisted review authorized after a user spot-check. "
            "The locked test is protected from tuning but is not an independent human-labelled test."
        ),
        "excluded": {"outdated": 28, "ambiguous": 2},
        "reviewed_candidates_sha256": checksum(reviewed_payload),
        "source_commit": json.loads((DATA / "expanded_manifest.json").read_text())["source_commit"],
        "test_locked": True,
        "test_status": "locked_ai_assisted_not_independent",
        "splits": {},
    }
    for name, cases in splits.items():
        payload = encoded(cases)
        (OUTPUT / f"{name}.json").write_bytes(payload)
        manifest["splits"][name] = {
            "count": len(cases),
            "supported": sum(case["expected_document_id"] is not None for case in cases),
            "unsupported": sum(case["expected_document_id"] is None for case in cases),
            "sha256": checksum(payload),
        }
    manifest_path.write_bytes(encoded(manifest))
    print("built development=42, validation=14, locked_test=14; excluded=30")


if __name__ == "__main__":
    main()
