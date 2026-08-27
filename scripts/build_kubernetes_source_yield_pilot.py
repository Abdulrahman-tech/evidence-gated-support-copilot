#!/usr/bin/env python3
"""Build a blind 60-case Kubernetes source-yield pilot without hosted models."""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.medusa_discussions import near_duplicate
from support_copilot.models import KnowledgeDocument


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "kubernetes"
POOL = DATA / "question_pool"
OUTPUT = DATA / "source_yield_pilot"
SEED = "kubernetes-source-yield-pilot-v1"
EXTERNAL_TAG_PREFIXES = (
    "amazon-",
    "apache-",
    "argocd",
    "azure-",
    "docker",
    "google-",
    "istio",
    "java",
    "kubernetes-helm",
    "nginx",
    "node.js",
    "python",
    "spring-",
)


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_key(case_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{case_id}".encode()).hexdigest()


def external_tags(tags: list[str]) -> list[str]:
    return sorted(
        tag
        for tag in tags
        if any(tag == prefix or tag.startswith(prefix) for prefix in EXTERNAL_TAG_PREFIXES)
    )


def select_diverse(rows: list[dict], target: int, max_per_area: int = 10) -> list[dict]:
    selected = []
    area_counts: collections.Counter[str] = collections.Counter()
    for row in rows:
        if area_counts[row["retrieved_area"]] >= max_per_area:
            continue
        if any(near_duplicate(row["question"], item["question"], 0.75) for item in selected):
            continue
        selected.append(row)
        area_counts[row["retrieved_area"]] += 1
        if len(selected) == target:
            return selected
    raise ValueError(f"only {len(selected)} diverse cases available; target is {target}")


def main() -> None:
    knowledge_path = DATA / "knowledge.json"
    knowledge_manifest_path = DATA / "manifest.json"
    pool_manifest_path = POOL / "manifest.json"
    accepted_path = POOL / "accepted_questions.json"
    challenge_path = POOL / "challenge_questions.json"
    knowledge_manifest = json.loads(knowledge_manifest_path.read_text())
    pool_manifest = json.loads(pool_manifest_path.read_text())
    if sha256(knowledge_path) != knowledge_manifest["knowledge_sha256"]:
        raise ValueError("Kubernetes knowledge checksum mismatch")
    if sha256(accepted_path) != pool_manifest["accepted_sha256"]:
        raise ValueError("accepted question checksum mismatch")
    if sha256(challenge_path) != pool_manifest["challenge_sha256"]:
        raise ValueError("challenge question checksum mismatch")

    documents = [
        KnowledgeDocument(**row)
        for row in json.loads(knowledge_path.read_text(encoding="utf-8"))
    ]
    documents_by_id = {document.document_id: document for document in documents}
    knowledge_base = KnowledgeBase(documents)

    def screened(path: Path, stratum: str) -> list[dict]:
        rows = []
        for candidate in json.loads(path.read_text(encoding="utf-8")):
            results = knowledge_base.search(candidate["question"], limit=3)
            top = results[0] if results else None
            rows.append(
                {
                    **candidate,
                    "screening_stratum": stratum,
                    "retrieval_confident": bool(results and retrieval_is_confident(results)),
                    "top_document_id": top.document_id if top else "",
                    "top_score": top.score if top else 0.0,
                    "retrieved_area": (
                        documents_by_id[top.document_id].product_area if top else "none"
                    ),
                    "external_tags": external_tags(candidate["source_tags"]),
                }
            )
        return rows

    accepted = screened(accepted_path, "likely_supported")
    challenge = screened(challenge_path, "likely_unsupported")
    supported_ranked = sorted(
        (row for row in accepted if row["retrieval_confident"]),
        key=lambda row: (
            len(row["external_tags"]),
            -row["top_score"],
            stable_key(row["case_id"]),
        ),
    )
    challenge_ranked = sorted(
        challenge,
        key=lambda row: (
            not bool(row["external_tags"]),
            row["top_score"],
            stable_key(row["case_id"]),
        ),
    )
    supported = select_diverse(supported_ranked, 30)
    challenge_selected = select_diverse(challenge_ranked, 30)
    selected = supported + challenge_selected
    if len({row["case_id"] for row in selected}) != 60:
        raise ValueError("pilot cases must be unique")
    if len({row["source_url"] for row in selected}) != 60:
        raise ValueError("pilot source URLs must be unique")

    screening = [
        {
            "case_id": row["case_id"],
            "screening_stratum": row["screening_stratum"],
            "retrieval_confident": row["retrieval_confident"],
            "top_document_id": row["top_document_id"],
            "top_score": row["top_score"],
            "retrieved_area": row["retrieved_area"],
            "external_tags": row["external_tags"],
        }
        for row in selected
    ]
    shuffled = sorted(selected, key=lambda row: stable_key(row["case_id"]))
    packet = [
        {
            "review_batch": index // 30 + 1,
            "case_id": row["case_id"],
            "source_url": row["source_url"],
            "question": row["question"],
            "source_created_at": row["source_created_at"],
            "source_tags": row["source_tags"],
            "author_display_name": row["author_display_name"],
            "author_url": row["author_url"],
            "content_license": row["content_license"],
            "reviewer_decision": "",
            "expected_document_id": "",
            "review_status": "pending",
            "reviewer_notes": "",
        }
        for index, row in enumerate(shuffled)
    ]

    OUTPUT.mkdir(parents=True, exist_ok=True)
    packet_bytes = encoded(packet)
    screening_bytes = encoded(screening)
    packet_path = OUTPUT / "review_packet.json"
    screening_path = OUTPUT / "private_screening_assignments.json"
    packet_path.write_bytes(packet_bytes)
    screening_path.write_bytes(screening_bytes)
    manifest = {
        "pilot_id": "kubernetes_source_yield_pilot_v1",
        "role": "source_yield_pilot_excluded_from_all_evaluation",
        "review_method": "manual_blind_against_pinned_official_corpus",
        "review_policy": (
            "The review packet contains no retriever result, suggested document, AI label, "
            "or screening stratum. Private screening assignments must remain hidden."
        ),
        "case_count": 60,
        "batch_counts": {"1": 30, "2": 30},
        "private_stratum_counts": {"likely_supported": 30, "likely_unsupported": 30},
        "knowledge_sha256": sha256(knowledge_path),
        "accepted_pool_sha256": sha256(accepted_path),
        "challenge_pool_sha256": sha256(challenge_path),
        "packet_sha256": hashlib.sha256(packet_bytes).hexdigest(),
        "private_screening_sha256": hashlib.sha256(screening_bytes).hexdigest(),
        "selection_seed": SEED,
        "hosted_model_calls": 0,
    }
    (OUTPUT / "manifest.json").write_bytes(encoded(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
