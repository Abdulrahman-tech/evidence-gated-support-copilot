#!/usr/bin/env python3
"""Fail closed unless retrieval data and quality meet production release gates."""

import json
from dataclasses import asdict
from pathlib import Path

from support_copilot.evaluation import load_cases, wilson_interval
from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.models import KnowledgeDocument
from support_copilot.readiness import ReadinessGate, maximum_gap_gate, minimum_gate


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "real_benchmark"


def measure(split: str) -> dict:
    case_name = "challenge_judged" if split == "challenge" else split
    cases = load_cases(BENCHMARK / f"{case_name}.json")
    documents = [
        KnowledgeDocument(**item)
        for item in json.loads(
            (BENCHMARK / f"{split}_knowledge.json").read_text(encoding="utf-8")
        )
    ]
    knowledge_base = KnowledgeBase(documents)
    supported = [case for case in cases if case.expected_document_id is not None]
    unsupported = [case for case in cases if case.expected_document_id is None]
    recall_hits = {1: 0, 3: 0}
    abstentions = 0
    for case in cases:
        results = knowledge_base.search(case.question, limit=3)
        confident = retrieval_is_confident(results)
        if case.expected_document_id is None:
            abstentions += not confident
            continue
        for k in recall_hits:
            recall_hits[k] += confident and any(
                result.document_id == case.expected_document_id
                for result in results[:k]
            )
    return {
        "supported_count": len(supported),
        "unsupported_count": len(unsupported),
        "recall_at_1": recall_hits[1] / len(supported),
        "recall_at_1_lower_95": wilson_interval(recall_hits[1], len(supported))[0],
        "recall_at_3": recall_hits[3] / len(supported),
        "recall_at_3_lower_95": wilson_interval(recall_hits[3], len(supported))[0],
        "unsupported_abstention": abstentions / len(unsupported),
        "unsupported_abstention_lower_95": wilson_interval(
            abstentions, len(unsupported)
        )[0],
    }


def main() -> None:
    manifest = json.loads((BENCHMARK / "manifest.json").read_text(encoding="utf-8"))
    metrics = {
        split: measure(split)
        for split in ("development", "validation", "challenge")
    }
    development = metrics["development"]
    validation = metrics["validation"]
    challenge = metrics["challenge"]
    gates = [
        ReadinessGate(
            "validation_supported_sample_size",
            validation["supported_count"] >= 200,
            str(validation["supported_count"]),
            ">= 200",
        ),
        ReadinessGate(
            "validation_unsupported_sample_size",
            validation["unsupported_count"] >= 100,
            str(validation["unsupported_count"]),
            ">= 100",
        ),
        ReadinessGate(
            "challenge_case_by_case_labels",
            manifest.get("challenge_review_status") == "human_adjudicated",
            manifest.get("challenge_review_status", "missing"),
            "human_adjudicated",
        ),
        ReadinessGate(
            "locked_test_full_human_review",
            manifest.get("test_review_status") == "human_reviewed",
            manifest.get("test_review_status", "missing"),
            "human_reviewed",
        ),
        ReadinessGate(
            "tenant_isolation_metadata",
            "tenant_assignment_sha256" in manifest,
            "present" if "tenant_assignment_sha256" in manifest else "missing",
            "present",
        ),
        minimum_gate(
            "validation_recall_at_1_lower_95",
            validation["recall_at_1_lower_95"],
            0.85,
        ),
        minimum_gate(
            "validation_recall_at_3_lower_95",
            validation["recall_at_3_lower_95"],
            0.90,
        ),
        minimum_gate(
            "validation_abstention_lower_95",
            validation["unsupported_abstention_lower_95"],
            0.95,
        ),
        maximum_gap_gate(
            "development_validation_recall_at_1_gap",
            development["recall_at_1"],
            validation["recall_at_1"],
            0.05,
        ),
        maximum_gap_gate(
            "development_validation_recall_at_3_gap",
            development["recall_at_3"],
            validation["recall_at_3"],
            0.05,
        ),
        minimum_gate(
            "challenge_recall_at_1_lower_95",
            challenge["recall_at_1_lower_95"],
            0.80,
        ),
        minimum_gate(
            "challenge_abstention_lower_95",
            challenge["unsupported_abstention_lower_95"],
            0.95,
        ),
    ]
    payload = {
        "ready": all(gate.passed for gate in gates),
        "metrics": metrics,
        "gates": [asdict(gate) for gate in gates],
        "locked_test_evaluated": False,
    }
    print(json.dumps(payload, indent=2))
    raise SystemExit(0 if payload["ready"] else 1)


if __name__ == "__main__":
    main()
