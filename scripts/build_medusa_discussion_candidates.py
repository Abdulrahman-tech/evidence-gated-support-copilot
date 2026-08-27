#!/usr/bin/env python3
"""Map authentic answered Medusa Q&A titles to the expanded official corpus."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.models import KnowledgeDocument


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
REVIEW = ROOT / "review" / "medusa_discussion_candidates.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    output = DATA / "discussion_candidates.json"
    if output.exists() and not args.rebuild:
        raise SystemExit("discussion candidates already exist; pass --rebuild to replace")

    sources = json.loads((DATA / "discussion_sources.json").read_text(encoding="utf-8"))
    documents = [
        KnowledgeDocument(**item)
        for item in json.loads((DATA / "knowledge_expanded.json").read_text(encoding="utf-8"))
    ]
    documents_by_id = {document.document_id: document for document in documents}
    knowledge_base = KnowledgeBase(documents)
    candidates = []
    for source in sources:
        results = knowledge_base.search(source["question"], limit=3)
        candidate = {
            **source,
            "suggested_product_area": (
                documents_by_id[results[0].document_id].product_area if results else ""
            ),
            "model_accepts": retrieval_is_confident(results),
            "top_score": results[0].score if results else 0.0,
            "reviewer_decision": "",
            "expected_document_id": "",
            "review_status": "pending",
            "review_notes": "",
        }
        for index in range(3):
            result = results[index] if index < len(results) else None
            position = index + 1
            candidate[f"top{position}_document_id"] = result.document_id if result else ""
            candidate[f"top{position}_title"] = result.title if result else ""
            candidate[f"top{position}_source"] = result.source if result else ""
            candidate[f"top{position}_product_area"] = (
                documents_by_id[result.document_id].product_area if result else ""
            )
        candidates.append(candidate)

    payload = (json.dumps(candidates, indent=2, sort_keys=True) + "\n").encode()
    output.write_bytes(payload)
    with REVIEW.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(candidates[0]))
        writer.writeheader()
        writer.writerows(candidates)

    manifest_path = DATA / "expanded_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "discussion_candidate_count": len(candidates),
            "discussion_candidate_sha256": hashlib.sha256(payload).hexdigest(),
            "discussion_candidate_source": (
                "Answered Q&A titles and URLs from the official Medusa GitHub Discussions; "
                "candidate mappings require adjudication."
            ),
        }
    )
    manifest_path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    )
    print(
        f"built {len(candidates)} authentic discussion candidates; "
        f"retriever accepted {sum(item['model_accepts'] for item in candidates)}"
    )


if __name__ == "__main__":
    main()
