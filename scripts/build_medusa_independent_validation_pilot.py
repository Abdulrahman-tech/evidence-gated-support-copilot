#!/usr/bin/env python3
"""Freeze a blind Medusa issue pilot for independent validation."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
BENCHMARK = DATA / "benchmark"
POOL = DATA / "candidate_pool"
FRESH_VALIDATION = DATA / "fresh_validation"
OUTPUT = DATA / "independent_validation_pilot"
CALIBRATION = ROOT / "artifacts" / "medusa_local_semantic_gate.json"
PILOT_SIZE = 30
SEED = "medusa-independent-validation-issue-pilot-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def rank(case_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{case_id}".encode()).hexdigest()


def select_stratified(rows: list[dict], metadata: dict[str, dict]) -> list[dict]:
    buckets: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for row in rows:
        source = metadata[row["case_id"]]
        buckets[
            (source["proposed_product_area"], source["support_intent"])
        ].append(row)
    for bucket in buckets.values():
        bucket.sort(key=lambda row: rank(row["case_id"]))

    selected: list[dict] = []
    strata = sorted(
        buckets,
        key=lambda item: hashlib.sha256(f"{SEED}:{item[0]}:{item[1]}".encode()).hexdigest(),
    )
    while len(selected) < PILOT_SIZE:
        added = False
        for stratum in strata:
            if buckets[stratum] and len(selected) < PILOT_SIZE:
                selected.append(buckets[stratum].pop(0))
                added = True
        if not added:
            break
    if len(selected) != PILOT_SIZE:
        raise ValueError(f"expected {PILOT_SIZE} pilot cases, found {len(selected)}")
    return selected


def build() -> tuple[list[dict], dict, dict]:
    packet_path = FRESH_VALIDATION / "validation_review_packet.json"
    packet_manifest_path = FRESH_VALIDATION / "validation_review_packet_manifest.json"
    sources_path = POOL / "sources.json"
    assignments_path = POOL / "assignments.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet_manifest = json.loads(packet_manifest_path.read_text(encoding="utf-8"))
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    assignments = json.loads(assignments_path.read_text(encoding="utf-8"))
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))

    if sha256(packet_path) != packet_manifest["packet_sha256"]:
        raise ValueError("fresh validation packet checksum mismatch")
    if any(row["review_status"] != "pending" or row["reviewer_decision"] for row in packet):
        raise ValueError("fresh validation candidates have already been labelled")
    if calibration["selection_status"] != "selected_for_independent_validation":
        raise ValueError("semantic candidate is not eligible for independent validation")

    source_by_id = {row["case_id"]: row for row in sources}
    assignment_by_id = {row["case_id"]: row for row in assignments}
    selected = select_stratified(packet, source_by_id)
    selected_ids = {row["case_id"] for row in selected}
    if any(assignment_by_id[case_id]["role"] != "validation" for case_id in selected_ids):
        raise ValueError("pilot contains a case outside the frozen validation role")
    protected_urls = {
        row.get("source_url")
        for split in ("development", "validation", "test")
        for row in json.loads((BENCHMARK / f"{split}.json").read_text(encoding="utf-8"))
    }
    if protected_urls & {row["source_url"] for row in selected}:
        raise ValueError("pilot overlaps an existing benchmark source")

    review_packet = [
        {
            "case_id": row["case_id"],
            "expected_document_id": "",
            "question": row["question"],
            "review_order": index,
            "review_status": "pending",
            "reviewer_decision": "",
            "reviewer_notes": "",
            "source_url": row["source_url"],
        }
        for index, row in enumerate(selected, start=1)
    ]
    review_bytes = encoded(review_packet)
    cohort_counts = collections.Counter(
        (
            source_by_id[row["case_id"]]["proposed_product_area"],
            source_by_id[row["case_id"]]["support_intent"],
        )
        for row in selected
    )
    manifest = {
        "pilot_id": "medusa_independent_validation_issue_pilot_v1",
        "status": "paused_scope_archive",
        "purpose": "unsupported_source_yield_and_abstention_pilot",
        "case_count": len(review_packet),
        "selection_seed": SEED,
        "selection_method": "deterministic_round_robin_by_product_area_and_support_intent",
        "source_type": "github_issue_report",
        "review_policy": (
            "Review source pages against the pinned official corpus without retriever "
            "results, semantic scores, model predictions, or earlier benchmark labels."
        ),
        "scope_limit": (
            "This issue-only cohort can validate unsupported abstention and source yield. "
            "It cannot establish supported recall unless it yields supported cases, and "
            "it is not a production qualification set."
        ),
        "packet_sha256": hashlib.sha256(review_bytes).hexdigest(),
        "fresh_validation_packet_sha256": sha256(packet_path),
        "candidate_pool_source_sha256": sha256(sources_path),
        "candidate_pool_assignment_sha256": sha256(assignments_path),
        "protected_benchmark_hashes": {
            split: sha256(BENCHMARK / f"{split}.json")
            for split in ("development", "validation", "test")
        },
        "cohort_counts": {
            f"{area}|{intent}": count
            for (area, intent), count in sorted(cohort_counts.items())
        },
        "blind_fields": [
            "review_order",
            "case_id",
            "question",
            "source_url",
            "reviewer_decision",
            "expected_document_id",
            "review_status",
            "reviewer_notes",
        ],
    }
    frozen_candidate = {
        "candidate": calibration["candidate"],
        "calibration_artifact_sha256": sha256(CALIBRATION),
        "calibration_scope": calibration["calibration_scope"],
        "knowledge_sha256": calibration["knowledge_sha256"],
        "model": calibration["model"],
        "thresholds": {
            key: calibration["selected"][key]
            for key in (
                "minimum_title_alignment",
                "minimum_evidence_alignment",
                "minimum_semantic_similarity",
            )
        },
        "frozen_before_review": True,
        "runtime_changed": False,
        "hosted_calls": 0,
        "locked_test_evaluated": False,
        "protected_splits_evaluated": [],
    }
    return review_packet, manifest, frozen_candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="intentionally replace an existing untouched pilot",
    )
    args = parser.parse_args()
    if OUTPUT.exists() and not args.rebuild:
        raise SystemExit(
            "independent-validation pilot already exists; pass --rebuild only before review"
        )
    review_packet, manifest, frozen_candidate = build()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "review_packet.json").write_bytes(encoded(review_packet))
    (OUTPUT / "manifest.json").write_bytes(encoded(manifest))
    (OUTPUT / "frozen_candidate.json").write_bytes(encoded(frozen_candidate))
    (OUTPUT / "reviewer_attestation.json").write_bytes(
        encoded(
            {
                "completed_at": "",
                "reviewed_without_model_or_retriever_outputs": False,
                "reviewer_id": "",
                "reviewer_type": "human",
            }
        )
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
