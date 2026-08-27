#!/usr/bin/env python3
"""Build AI-assisted evidence suggestions for development candidates only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.models import KnowledgeDocument


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    assignments = json.loads(args.assignments.read_text(encoding="utf-8"))
    documents = [
        KnowledgeDocument(**item)
        for item in json.loads(args.knowledge.read_text(encoding="utf-8"))
    ]
    roles = {item["case_id"]: item["role"] for item in assignments}
    development = [item for item in sources if roles[item["case_id"]] == "development"]
    if len(development) != 521:
        raise ValueError(f"expected 521 frozen development cases, found {len(development)}")
    if any(roles[item["case_id"]] != "development" for item in development):
        raise ValueError("non-development case entered the review packet")

    knowledge_base = KnowledgeBase(documents)
    documents_by_id = {document.document_id: document for document in documents}
    packet = []
    for source in development:
        results = knowledge_base.search(source["question"], limit=3, tenant_id="medusa")
        confident = retrieval_is_confident(results)
        row = {
            "case_id": source["case_id"],
            "source_url": source["source_url"],
            "original_question": source["question"],
            "reviewed_question": source["question"],
            "proposed_product_area": source["proposed_product_area"],
            "support_intent": source["support_intent"],
            "source_labels": source["source_labels"],
            "retriever_confident": confident,
            "suggested_decision": "supported" if confident else "needs_manual_decision",
            "suggested_document_id": results[0].document_id if confident else "",
            "reviewer_decision": "",
            "expected_document_id": "",
            "review_status": "pending",
            "review_notes": "",
        }
        for position in range(3):
            result = results[position] if position < len(results) else None
            number = position + 1
            document = documents_by_id[result.document_id] if result else None
            row[f"top{number}_document_id"] = result.document_id if result else ""
            row[f"top{number}_title"] = result.title if result else ""
            row[f"top{number}_product_area"] = document.product_area if document else ""
            row[f"top{number}_source"] = result.source if result else ""
            row[f"top{number}_passage"] = result.passage if result else ""
            row[f"top{number}_score"] = result.score if result else 0.0
        packet.append(row)

    packet.sort(key=lambda item: (not item["retriever_confident"], item["case_id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(packet, indent=2, sort_keys=True) + "\n").encode()
    args.output.write_bytes(payload)
    summary = {
        "case_count": len(packet),
        "retriever_confident_count": sum(item["retriever_confident"] for item in packet),
        "manual_decision_count": sum(not item["retriever_confident"] for item in packet),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "review_method": "ai_assisted_development_only",
        "blind_roles_included": False,
    }
    (args.output.parent / "development_review_packet_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
