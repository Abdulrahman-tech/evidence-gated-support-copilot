#!/usr/bin/env python3
"""Apply fail-closed automated rules to development evidence suggestions."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path


RULE_VERSION = "development_direct_answer_v2"
REVIEW_METHOD = "automated_direct_answer_candidate_development_only"

INSTRUCTION_PATTERN = re.compile(
    r"\b(how(?:\s+do|\s+to)?|explain|install|configure|set\s*up|create|add|use|"
    r"implement|enable|disable|integrate|deploy|run|customi[sz]e|manage|update|"
    r"retrieve|fetch|list)\b",
    re.IGNORECASE,
)
DEFECT_PATTERN = re.compile(
    r"\b(error|fail(?:s|ed|ure)?|broken|wrong|incorrect|bug|issue|does\s+not|"
    r"doesn.t|not\s+working|unexpected|missing|crash(?:es|ed)?|hangs?|duplicate|"
    r"race\s+condition|out\s+of\s+memory|responds?\s+with|throws?|rejects?|"
    r"disappears?|not\s+recognized|not\s+include|not\s+support|"
    r"delet(?:e|es|ed|ing)|problems?|premature|forged)\b",
    re.IGNORECASE,
)


def decide(row: dict) -> tuple[str, str | None, str]:
    ratio = row["top1_score"] / row["top2_score"] if row["top2_score"] else float("inf")
    area_aligned = (
        row["proposed_product_area"] != "other"
        and row["proposed_product_area"] == row["top1_product_area"]
    )
    question = row["reviewed_question"]
    direct_instructional_request = bool(INSTRUCTION_PATTERN.search(question))
    defect_like = bool(DEFECT_PATTERN.search(question))
    if (
        row["retriever_confident"]
        and area_aligned
        and ratio >= 1.2
        and row["support_intent"] in {"documentation_gap", "technical_request"}
        and direct_instructional_request
        and not defect_like
    ):
        return (
            "supported",
            row["top1_document_id"],
            "direct non-defect instructional request with strong area-aligned evidence",
        )
    return (
        "deferred",
        None,
        "automation cannot establish a direct answer; unsupported labels require human review",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet = json.loads(args.packet.read_text(encoding="utf-8"))
    decisions = []
    for row in packet:
        decision, document_id, reason = decide(row)
        decisions.append(
            {
                "case_id": row["case_id"],
                "reviewed_question": row["reviewed_question"],
                "reviewer_decision": decision,
                "expected_document_id": document_id,
                "review_status": "pending_audit" if decision == "supported" else "deferred",
                "review_notes": f"{RULE_VERSION}: {reason}",
                "review_method": REVIEW_METHOD,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(decisions, indent=2, sort_keys=True) + "\n").encode()
    args.output.write_bytes(payload)
    counts = collections.Counter(item["reviewer_decision"] for item in decisions)
    manifest = {
        "rule_version": RULE_VERSION,
        "case_count": len(decisions),
        "decision_counts": dict(sorted(counts.items())),
        "candidate_count": counts["supported"],
        "usable_count": 0,
        "deferred_count": counts["deferred"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "review_method": REVIEW_METHOD,
        "blind_roles_touched": False,
        "import_allowed": False,
        "requires_new_quality_audit": True,
    }
    (args.output.parent / "automated_development_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
