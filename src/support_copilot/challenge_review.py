"""Export and validate human adjudication of challenge-set unsupported cases."""

import csv
import hashlib
import json
from pathlib import Path

from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.models import KnowledgeDocument


REVIEW_FIELDS = (
    "case_id",
    "question",
    "review_priority",
    "model_accepts",
    "top_score",
    "top_to_second_ratio",
    "reviewer_decision",
    "relevant_document_id",
    "review_status",
    "review_notes",
    "top1_document_id",
    "top1_evidence",
    "top2_document_id",
    "top2_evidence",
    "top3_document_id",
    "top3_evidence",
    "source_conversation_id",
    "source_tweet_id",
)


def challenge_case_id(case: dict) -> str:
    identity = json.dumps(
        {
            "question": case["question"],
            "source_conversation_id": case["source_conversation_id"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "challenge-" + hashlib.sha256(identity.encode()).hexdigest()[:12]


def export_challenge_review(
    challenge_path: Path,
    knowledge_path: Path,
    output_path: Path,
) -> None:
    cases = json.loads(challenge_path.read_text(encoding="utf-8"))
    unsupported = [case for case in cases if case["expected_document_id"] is None]
    documents = [
        KnowledgeDocument(**item)
        for item in json.loads(knowledge_path.read_text(encoding="utf-8"))
    ]
    knowledge_base = KnowledgeBase(documents)

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for case in unsupported:
            results = knowledge_base.search(case["question"], limit=3)
            model_accepts = retrieval_is_confident(results)
            top_score = results[0].score if results else 0.0
            ratio = (
                results[0].score / results[1].score
                if len(results) > 1 and results[1].score
                else 0.0
            )
            result_fields = {}
            for position in range(3):
                result = results[position] if position < len(results) else None
                number = position + 1
                result_fields[f"top{number}_document_id"] = (
                    result.document_id if result else ""
                )
                result_fields[f"top{number}_evidence"] = (
                    f"{result.title} — {result.passage} (score {result.score:.4f})"
                    if result
                    else "No matching document"
                )
            writer.writerow(
                {
                    "case_id": challenge_case_id(case),
                    "question": case["question"],
                    "review_priority": "high" if model_accepts else "standard",
                    "model_accepts": "yes" if model_accepts else "no",
                    "top_score": f"{top_score:.4f}",
                    "top_to_second_ratio": f"{ratio:.4f}",
                    "reviewer_decision": "",
                    "relevant_document_id": "",
                    "review_status": "pending",
                    "review_notes": "",
                    **result_fields,
                    "source_conversation_id": case["source_conversation_id"],
                    "source_tweet_id": case["source_tweet_id"],
                }
            )


def import_challenge_review(
    review_path: Path,
    challenge_path: Path,
    knowledge_path: Path,
) -> tuple[list[dict], dict]:
    original = json.loads(challenge_path.read_text(encoding="utf-8"))
    knowledge_ids = {
        item["document_id"]
        for item in json.loads(knowledge_path.read_text(encoding="utf-8"))
    }
    unsupported = {
        challenge_case_id(case): case
        for case in original
        if case["expected_document_id"] is None
    }
    with review_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    actual_ids = [row.get("case_id", "") for row in rows]
    if len(actual_ids) != len(unsupported) or set(actual_ids) != set(unsupported):
        raise ValueError("review must contain every unsupported challenge case_id exactly once")

    reviewed_cases = []
    decision_counts = {"unsupported": 0, "answerable": 0, "ambiguous": 0}
    for row in rows:
        case_id = row["case_id"]
        if row.get("review_status", "").strip().lower() != "approved":
            raise ValueError(f"{case_id}: review_status must be approved")
        decision = row.get("reviewer_decision", "").strip().lower()
        if decision not in decision_counts:
            raise ValueError(
                f"{case_id}: reviewer_decision must be unsupported, answerable, or ambiguous"
            )
        relevant_document_id = row.get("relevant_document_id", "").strip()
        if decision == "answerable":
            if relevant_document_id not in knowledge_ids:
                raise ValueError(f"{case_id}: answerable cases require a valid document id")
        elif relevant_document_id:
            raise ValueError(f"{case_id}: only answerable cases may have a document id")

        decision_counts[decision] += 1
        if decision == "ambiguous":
            continue
        case = dict(unsupported[case_id])
        case["expected_document_id"] = (
            relevant_document_id if decision == "answerable" else None
        )
        case["adjudication"] = {
            "decision": decision,
            "review_notes": row.get("review_notes", "").strip(),
        }
        reviewed_cases.append(case)

    supported = [case for case in original if case["expected_document_id"] is not None]
    judged = supported + reviewed_cases
    judged.sort(key=lambda case: challenge_case_id(case))
    return judged, decision_counts
