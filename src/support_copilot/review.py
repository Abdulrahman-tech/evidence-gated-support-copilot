"""Export and validate the human review of the locked test split."""

import csv
import hashlib
import json
from pathlib import Path


REVIEW_FIELDS = (
    "case_id",
    "question",
    "expected_document_id",
    "category",
    "difficulty",
    "review_status",
    "review_notes",
    "provenance",
    "source_conversation_id",
    "source_tweet_id",
    "expected_knowledge_title",
    "expected_knowledge_text",
    "review_scope",
)


def case_id(case: dict) -> str:
    identity = json.dumps(
        {"question": case["question"], "expected_document_id": case["expected_document_id"]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "test-" + hashlib.sha256(identity.encode()).hexdigest()[:12]


def export_review_csv(
    test_path: Path,
    policies_path: Path,
    output_path: Path,
    fast_review: bool = False,
) -> None:
    cases = json.loads(test_path.read_text(encoding="utf-8"))
    manual_real_ids = set()
    if fast_review:
        real_cases = [case for case in cases if case.get("provenance") == "tweetsumm_real_conversation"]
        sampled = sorted(
            real_cases,
            key=lambda case: hashlib.sha256(f"manual-review:{case_id(case)}".encode()).hexdigest(),
        )[:20]
        manual_real_ids = {case_id(case) for case in sampled}
    policies = {
        item["document_id"]: item
        for item in json.loads(policies_path.read_text(encoding="utf-8"))
    }
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for case in cases:
            policy = policies.get(case["expected_document_id"], {})
            requires_manual_review = (
                not fast_review
                or case.get("provenance") != "tweetsumm_real_conversation"
                or case_id(case) in manual_real_ids
            )
            writer.writerow(
                {
                    "case_id": case_id(case),
                    **case,
                    "expected_document_id": case["expected_document_id"] or "",
                    "review_status": "pending" if requires_manual_review else "auto_checked",
                    "review_notes": "" if requires_manual_review else (
                        "Passed duplicate, schema, redaction, and source-integrity checks; "
                        "not individually human-reviewed."
                    ),
                    "provenance": case.get("provenance", "synthetic"),
                    "source_conversation_id": case.get("source_conversation_id", ""),
                    "source_tweet_id": case.get("source_tweet_id", ""),
                    "expected_knowledge_title": policy.get("title", "Unsupported safety case"),
                    "expected_knowledge_text": policy.get("text", "No knowledge document should answer this question."),
                    "review_scope": "manual_required" if requires_manual_review else "automated_checks_only",
                }
            )


def validate_review_csv(review_path: Path, test_path: Path, policies_path: Path) -> list[dict]:
    original = json.loads(test_path.read_text(encoding="utf-8"))
    expected_ids = {case_id(case) for case in original}
    policy_ids = {
        item["document_id"]
        for item in json.loads(policies_path.read_text(encoding="utf-8"))
    }
    with review_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    actual_ids = {row.get("case_id", "") for row in rows}
    if len(rows) != len(expected_ids) or actual_ids != expected_ids:
        raise ValueError("review must contain every original case_id exactly once")

    fast_review = any(
        row.get("review_scope", "").strip().lower() == "automated_checks_only"
        for row in rows
    )
    expected_scopes = {}
    if fast_review:
        real_cases = [case for case in original if case.get("provenance") == "tweetsumm_real_conversation"]
        sampled = sorted(
            real_cases,
            key=lambda case: hashlib.sha256(f"manual-review:{case_id(case)}".encode()).hexdigest(),
        )[:20]
        manual_real_ids = {case_id(case) for case in sampled}
        expected_scopes = {
            case_id(case): (
                "manual_required"
                if case.get("provenance") != "tweetsumm_real_conversation" or case_id(case) in manual_real_ids
                else "automated_checks_only"
            )
            for case in original
        }

    approved = []
    for row in rows:
        status = row.get("review_status", "").strip().lower()
        scope = row.get("review_scope", "").strip().lower()
        if fast_review and scope != expected_scopes[row["case_id"]]:
            raise ValueError(f"{row.get('case_id')}: review_scope does not match the locked review sample")
        if scope == "automated_checks_only":
            if status != "auto_checked":
                raise ValueError(f"{row.get('case_id')}: automated-check rows must remain auto_checked")
        elif status != "approved":
            raise ValueError(f"{row.get('case_id')}: manual-review rows must be approved before import")
        document_id = row.get("expected_document_id", "").strip() or None
        if document_id is not None and document_id not in policy_ids:
            raise ValueError(f"{row['case_id']}: unknown expected_document_id {document_id}")
        question = row.get("question", "").strip()
        if not question:
            raise ValueError(f"{row['case_id']}: question cannot be empty")
        approved.append(
            {
                "question": question,
                "expected_document_id": document_id,
                "category": row.get("category", "").strip(),
                "difficulty": row.get("difficulty", "").strip(),
                "provenance": row.get("provenance", "").strip(),
                "source_conversation_id": row.get("source_conversation_id", "").strip(),
                "source_tweet_id": row.get("source_tweet_id", "").strip(),
            }
        )
    return approved
