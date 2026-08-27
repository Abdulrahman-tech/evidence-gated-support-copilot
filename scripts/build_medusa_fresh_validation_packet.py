#!/usr/bin/env python3
"""Build a blind manual-review packet from the frozen Medusa validation role."""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
POOL = DATA / "candidate_pool"
BENCHMARK = DATA / "benchmark"
OUTPUT = DATA / "fresh_validation"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def benchmark_urls() -> set[str]:
    urls = set()
    for path in BENCHMARK.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            urls.update(row.get("source_url", "") for row in payload)
    return {url for url in urls if url}


def main() -> None:
    sources_path = POOL / "sources.json"
    source_manifest_path = POOL / "manifest.json"
    assignments_path = POOL / "assignments.json"
    assignment_manifest_path = POOL / "assignment_manifest.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    assignments = json.loads(assignments_path.read_text(encoding="utf-8"))
    assignment_manifest = json.loads(
        assignment_manifest_path.read_text(encoding="utf-8")
    )
    if sha256(sources_path) != source_manifest["sha256"]:
        raise ValueError("candidate source checksum mismatch")
    if sha256(assignments_path) != assignment_manifest["assignment_sha256"]:
        raise ValueError("candidate role assignment checksum mismatch")

    roles = {row["case_id"]: row for row in assignments}
    if len(roles) != len(assignments):
        raise ValueError("candidate assignments must contain unique case IDs")
    validation = [
        row for row in sources if roles[row["case_id"]]["role"] == "validation"
    ]
    if len(validation) != assignment_manifest["role_counts"]["validation"]:
        raise ValueError("validation role count does not match frozen manifest")
    locked_groups = {
        row["leakage_group_id"]
        for row in assignments
        if row["role"] in {"development", "locked_test", "reserve"}
    }
    validation_groups = {
        roles[row["case_id"]]["leakage_group_id"] for row in validation
    }
    if validation_groups & locked_groups:
        raise ValueError("topic leakage group crosses frozen roles")
    overlap = {row["source_url"] for row in validation} & benchmark_urls()
    if overlap:
        raise ValueError(f"validation sources overlap existing benchmark: {overlap}")

    validation.sort(
        key=lambda row: (
            row["proposed_product_area"],
            hashlib.sha256(
                f"medusa-fresh-validation-v1:{row['case_id']}".encode()
            ).hexdigest(),
        )
    )
    packet = []
    for index, row in enumerate(validation):
        packet.append(
            {
                "review_batch": index // 97 + 1,
                "case_id": row["case_id"],
                "source_url": row["source_url"],
                "question": row["question"],
                "proposed_product_area": row["proposed_product_area"],
                "support_intent": row["support_intent"],
                "source_type": row["source_type"],
                "source_labels": row.get("source_labels", []),
                "body_word_count": row.get("body_word_count", 0),
                "reviewer_decision": "",
                "expected_document_id": "",
                "review_status": "pending",
                "reviewer_notes": "",
            }
        )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    packet_path = OUTPUT / "validation_review_packet.json"
    packet_bytes = encoded(packet)
    packet_path.write_bytes(packet_bytes)
    manifest = {
        "packet_id": "medusa_fresh_validation_20260825",
        "role": "validation",
        "review_method": "independent_manual_blind",
        "review_policy": (
            "No retriever output, model prediction, suggested label, or AI evidence "
            "is included. Reviewers use source pages and the pinned official corpus."
        ),
        "case_count": len(packet),
        "batch_counts": dict(
            sorted(collections.Counter(row["review_batch"] for row in packet).items())
        ),
        "product_area_counts": dict(
            sorted(
                collections.Counter(
                    row["proposed_product_area"] for row in packet
                ).items()
            )
        ),
        "support_intent_counts": dict(
            sorted(
                collections.Counter(row["support_intent"] for row in packet).items()
            )
        ),
        "source_sha256": sha256(sources_path),
        "assignment_sha256": sha256(assignments_path),
        "packet_sha256": hashlib.sha256(packet_bytes).hexdigest(),
        "knowledge_sha256": sha256(DATA / "knowledge_expanded.json"),
        "protected_benchmark_hashes": {
            name: sha256(BENCHMARK / f"{name}.json")
            for name in ("development", "validation", "test")
        },
    }
    (OUTPUT / "validation_review_packet_manifest.json").write_bytes(
        encoded(manifest)
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
