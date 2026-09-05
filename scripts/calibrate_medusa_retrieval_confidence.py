#!/usr/bin/env python3
"""Test the lexical confidence-gate family on Medusa development only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from support_copilot.evaluation import load_cases, retrieval_confidence_metrics
from support_copilot.knowledge import (
    DEFAULT_MINIMUM_SCORE,
    DEFAULT_MINIMUM_SCORE_RATIO,
    KnowledgeBase,
)
from support_copilot.models import KnowledgeDocument


ROOT = Path(__file__).resolve().parents[1]
MEDUSA = ROOT / "data" / "medusa"
BENCHMARK = MEDUSA / "benchmark"
EXPECTED_VALIDATION_SHA256 = (
    "bd723cc8ea874734d8d6f6e715d8859cc38027e23e75107594d351644d9f494a"
)
EXPECTED_LOCKED_TEST_SHA256 = (
    "ea7e88dd4b9cbb4277528a33a9d7e9949fafb6ace5f133976c99424c2d899cfd"
)
MINIMUM_SUPPORTED_RECALL_AT_3 = 0.80
MINIMUM_UNSUPPORTED_ABSTENTION = 0.80


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


measure = retrieval_confidence_metrics


def calibrate() -> dict:
    development_path = BENCHMARK / "development.json"
    validation_path = BENCHMARK / "validation.json"
    locked_test_path = BENCHMARK / "test.json"
    knowledge_path = MEDUSA / "knowledge_expanded.json"
    benchmark_manifest = json.loads((BENCHMARK / "manifest.json").read_text())
    knowledge_manifest = json.loads((MEDUSA / "expanded_manifest.json").read_text())

    development_sha256 = sha256(development_path)
    validation_sha256 = sha256(validation_path)
    locked_test_sha256 = sha256(locked_test_path)
    knowledge_sha256 = sha256(knowledge_path)
    if development_sha256 != benchmark_manifest["splits"]["development"]["sha256"]:
        raise ValueError("Medusa development checksum mismatch")
    if validation_sha256 != EXPECTED_VALIDATION_SHA256:
        raise ValueError("protected validation split changed")
    if locked_test_sha256 != EXPECTED_LOCKED_TEST_SHA256:
        raise ValueError("protected locked test changed")
    if knowledge_sha256 != knowledge_manifest["knowledge_sha256"]:
        raise ValueError("Medusa knowledge checksum mismatch")

    cases = load_cases(development_path)
    documents = [
        KnowledgeDocument(**row)
        for row in json.loads(knowledge_path.read_text(encoding="utf-8"))
    ]
    knowledge_base = KnowledgeBase(documents)
    ranked = [
        knowledge_base.search(case.question, limit=3, tenant_id="medusa")
        for case in cases
    ]
    supported_count = sum(case.expected_document_id is not None for case in cases)
    raw_hits_at_3 = sum(
        any(result.document_id == case.expected_document_id for result in results[:3])
        for case, results in zip(cases, ranked)
        if case.expected_document_id is not None
    )

    scores = sorted(
        {0.0, DEFAULT_MINIMUM_SCORE}
        | {results[0].score for results in ranked if results}
    )
    ratios = sorted(
        {1.0, DEFAULT_MINIMUM_SCORE_RATIO}
        | {
            results[0].score / results[1].score
            for results in ranked
            if len(results) > 1
        }
    )
    candidates = [
        measure(cases, ranked, score, ratio)
        for score in scores
        for ratio in ratios
    ]
    feasible = [
        candidate
        for candidate in candidates
        if candidate["supported_recall_at_3"] >= MINIMUM_SUPPORTED_RECALL_AT_3
        and candidate["unsupported_abstention"] >= MINIMUM_UNSUPPORTED_ABSTENTION
    ]
    selected = (
        max(
            feasible,
            key=lambda candidate: (
                candidate["unsupported_abstention"],
                candidate["supported_recall_at_3"],
                candidate["supported_recall_at_1"],
                -candidate["accepted_count"],
            ),
        )
        if feasible
        else None
    )
    best_abstention_while_preserving_recall = max(
        (
            candidate
            for candidate in candidates
            if candidate["supported_recall_at_3"] >= MINIMUM_SUPPORTED_RECALL_AT_3
        ),
        key=lambda candidate: (
            candidate["unsupported_abstention"],
            candidate["supported_recall_at_1"],
            -candidate["accepted_count"],
        ),
    )
    best_recall_while_preserving_abstention = max(
        (
            candidate
            for candidate in candidates
            if candidate["unsupported_abstention"] >= MINIMUM_UNSUPPORTED_ABSTENTION
        ),
        key=lambda candidate: (
            candidate["supported_recall_at_3"],
            candidate["supported_recall_at_1"],
            candidate["unsupported_abstention"],
        ),
    )

    return {
        "calibration_scope": "medusa_development_only",
        "calibration_status": (
            "viable_threshold_found" if feasible else "no_viable_score_ratio_threshold"
        ),
        "selection": selected,
        "runtime_defaults_changed": False,
        "decision": (
            "Do not loosen the production confidence gate. Replace or augment the "
            "score-ratio feature before another hosted-model evaluation."
        ),
        "requirements": {
            "minimum_supported_recall_at_3": MINIMUM_SUPPORTED_RECALL_AT_3,
            "minimum_unsupported_abstention": MINIMUM_UNSUPPORTED_ABSTENTION,
        },
        "development": {
            "case_count": len(cases),
            "supported_count": supported_count,
            "unsupported_count": len(cases) - supported_count,
            "raw_candidate_recall_at_3": raw_hits_at_3 / supported_count,
            "sha256": development_sha256,
        },
        "baseline": measure(
            cases,
            ranked,
            DEFAULT_MINIMUM_SCORE,
            DEFAULT_MINIMUM_SCORE_RATIO,
        ),
        "best_abstention_while_preserving_recall": (
            best_abstention_while_preserving_recall
        ),
        "best_recall_while_preserving_abstention": (
            best_recall_while_preserving_abstention
        ),
        "candidate_threshold_count": len(candidates),
        "knowledge_sha256": knowledge_sha256,
        "protected_splits_evaluated": [],
        "protected_split_checksums": {
            "validation": validation_sha256,
            "locked_test": locked_test_sha256,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "medusa_confidence_gate_calibration.json",
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(calibrate(), indent=2, sort_keys=True) + "\n"
    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output}")
    print(rendered, end="")


if __name__ == "__main__":
    main()
