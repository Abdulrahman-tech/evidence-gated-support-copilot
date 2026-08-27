#!/usr/bin/env python3
"""Create reviewable benchmark candidates from public official Medusa issues."""

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.models import KnowledgeDocument


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
REVIEW = ROOT / "review" / "medusa_issue_candidates.csv"
PREFIX = re.compile(r"^\s*\[(?:bug|feature|improvement)]\s*:\s*", re.I)
AREA_PATTERNS = (
    ("auth", re.compile(r"\b(auth|oauth|login|password|session|token)\b", re.I)),
    ("inventory", re.compile(r"\b(inventory|reservation|stock|location)\b", re.I)),
    ("payment", re.compile(r"\b(payment|refund|capture|stripe|currency)\b", re.I)),
    ("fulfillment", re.compile(r"\b(fulfillment|shipping|delivery)\b", re.I)),
    ("order", re.compile(r"\b(order|return|exchange|claim|draft)\b", re.I)),
    ("product", re.compile(r"\b(product|variant|price|pricing|promotion)\b", re.I)),
    ("customer", re.compile(r"\bcustomer\b", re.I)),
)


def product_area(title: str) -> str:
    return next(
        (area for area, pattern in AREA_PATTERNS if pattern.search(title)),
        "out_of_scope",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issues", type=Path, nargs="+", required=True)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    output = DATA / "issue_candidates.json"
    if output.exists() and not args.rebuild:
        raise SystemExit("Medusa issue candidates already exist; pass --rebuild to replace")

    items = [
        item
        for path in args.issues
        for item in json.loads(path.read_text(encoding="utf-8"))
        if "pull_request" not in item
    ]
    issues = {item["number"]: item for item in items}
    documents_payload = json.loads((DATA / "knowledge.json").read_text(encoding="utf-8"))
    documents = [KnowledgeDocument(**item) for item in documents_payload]
    documents_by_id = {document.document_id: document for document in documents}
    knowledge_base = KnowledgeBase(documents)
    candidates = []
    for number, issue in sorted(issues.items(), reverse=True):
        question = PREFIX.sub("", issue["title"]).strip()
        if not (30 <= len(question) <= 180 and len(question.split()) >= 5):
            continue
        results = knowledge_base.search(question, limit=3)
        confident = retrieval_is_confident(results)
        candidate = {
            "case_id": f"medusa-issue-{number}",
            "source_url": issue["html_url"],
            "question": question,
            "source_state": issue["state"],
            "source_labels": [label["name"] for label in issue["labels"]],
            "proposed_product_area": product_area(question),
            "model_accepts": confident,
            "top_score": results[0].score if results else 0.0,
            "reviewer_decision": "",
            "expected_document_id": "",
            "review_status": "pending",
            "review_notes": "",
        }
        for index in range(3):
            result = results[index] if index < len(results) else None
            position = index + 1
            candidate[f"top{position}_document_id"] = (
                result.document_id if result else ""
            )
            candidate[f"top{position}_title"] = result.title if result else ""
            candidate[f"top{position}_source"] = result.source if result else ""
            if result:
                candidate[f"top{position}_product_area"] = documents_by_id[
                    result.document_id
                ].product_area
            else:
                candidate[f"top{position}_product_area"] = ""
        candidates.append(candidate)
    if len(candidates) < 100:
        raise ValueError(f"expected at least 100 usable issue candidates, found {len(candidates)}")

    candidate_bytes = (
        json.dumps(candidates, indent=2, sort_keys=True) + "\n"
    ).encode()
    output.write_bytes(candidate_bytes)
    fieldnames = list(candidates[0])
    with REVIEW.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    **candidate,
                    "source_labels": " | ".join(candidate["source_labels"]),
                    "model_accepts": "yes" if candidate["model_accepts"] else "no",
                }
            )

    manifest_path = DATA / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["issue_candidate_count"] = len(candidates)
    manifest["issue_candidate_sha256"] = hashlib.sha256(candidate_bytes).hexdigest()
    manifest["issue_candidate_source"] = (
        "Public issues from https://github.com/medusajs/medusa; titles only, "
        "pending human review and document mapping"
    )
    manifest_path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    )
    print(f"built {len(candidates)} authentic Medusa issue candidates for review")


if __name__ == "__main__":
    main()
