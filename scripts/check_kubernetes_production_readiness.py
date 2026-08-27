#!/usr/bin/env python3
"""Fail-closed release gate for the Kubernetes Evidence Copilot."""

import argparse
import json
from pathlib import Path

from support_copilot.evaluation import load_cases, wilson_interval
from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.models import KnowledgeDocument


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "data" / "kubernetes" / "benchmark"
KNOWLEDGE = ROOT / "data" / "kubernetes" / "knowledge.json"


def gate(name: str, passed: bool, observed: object, required: str) -> dict:
    return {
        "name": name,
        "passed": passed,
        "observed": str(observed).lower() if isinstance(observed, bool) else str(observed),
        "required": required,
    }


def measure(path: Path, knowledge_base: KnowledgeBase) -> tuple[dict, set[str]]:
    cases = load_cases(path)
    supported = [case for case in cases if case.expected_document_id is not None]
    unsupported = [case for case in cases if case.expected_document_id is None]
    hits_at_1 = 0
    hits_at_3 = 0
    abstentions = 0
    for case in cases:
        results = knowledge_base.search(case.question, limit=3)
        confident = retrieval_is_confident(results)
        if case.expected_document_id is None:
            abstentions += int(not confident)
        else:
            hits_at_1 += int(
                confident and results[0].document_id == case.expected_document_id
            )
            hits_at_3 += int(
                confident
                and any(
                    result.document_id == case.expected_document_id
                    for result in results[:3]
                )
            )

    def metric(successes: int, total: int) -> tuple[float, float]:
        if total == 0:
            return 0.0, 0.0
        return successes / total, wilson_interval(successes, total)[0]

    recall_at_1, recall_at_1_lower = metric(hits_at_1, len(supported))
    recall_at_3, recall_at_3_lower = metric(hits_at_3, len(supported))
    abstention, abstention_lower = metric(abstentions, len(unsupported))
    independent = sum(
        case.review_method == "independent_human_review" for case in cases
    )
    return (
        {
            "case_count": len(cases),
            "supported_count": len(supported),
            "unsupported_count": len(unsupported),
            "independently_reviewed_count": independent,
            "recall_at_1": recall_at_1,
            "recall_at_1_lower_95": recall_at_1_lower,
            "recall_at_3": recall_at_3,
            "recall_at_3_lower_95": recall_at_3_lower,
            "unsupported_abstention": abstention,
            "unsupported_abstention_lower_95": abstention_lower,
        },
        {case.case_id for case in cases},
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--include-locked-test", action="store_true")
    args = parser.parse_args()

    required = ["manifest.json", "development.json", "validation.json"]
    if args.include_locked_test:
        required.append("locked_test.json")
    missing = [name for name in required if not (args.benchmark_dir / name).is_file()]
    if missing:
        payload = {
            "ready": False,
            "product": "kubernetes_evidence_copilot",
            "metrics": {},
            "gates": [
                gate("independent_benchmark_complete", False, ", ".join(missing), "no missing files"),
                gate(
                    "locked_test_evaluated",
                    False,
                    args.include_locked_test,
                    "true on the one-time release run",
                ),
            ],
            "locked_test_evaluated": False,
        }
        print(json.dumps(payload, indent=2))
        raise SystemExit(1)

    manifest = json.loads(
        (args.benchmark_dir / "manifest.json").read_text(encoding="utf-8")
    )
    documents = [
        KnowledgeDocument(**item)
        for item in json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    ]
    knowledge_base = KnowledgeBase(documents)
    development, development_ids = measure(
        args.benchmark_dir / "development.json", knowledge_base
    )
    validation, validation_ids = measure(
        args.benchmark_dir / "validation.json", knowledge_base
    )
    metrics = {"development": development, "validation": validation}
    locked_ids: set[str] = set()
    if args.include_locked_test:
        locked, locked_ids = measure(
            args.benchmark_dir / "locked_test.json", knowledge_base
        )
        metrics["locked_test"] = locked

    overlap = len(
        (development_ids & validation_ids)
        | (development_ids & locked_ids)
        | (validation_ids & locked_ids)
    )
    all_reviewed = all(
        item["independently_reviewed_count"] == item["case_count"]
        for item in metrics.values()
    )
    gates = [
        gate("independent_human_review", all_reviewed, all_reviewed, "true"),
        gate("split_overlap", overlap == 0, overlap, "0"),
        gate(
            "locked_test_not_used_for_tuning",
            manifest.get("locked_test_used_for_tuning") is False,
            manifest.get("locked_test_used_for_tuning", "missing"),
            "false",
        ),
        gate("validation_supported_sample_size", validation["supported_count"] >= 200, validation["supported_count"], ">= 200"),
        gate("validation_unsupported_sample_size", validation["unsupported_count"] >= 100, validation["unsupported_count"], ">= 100"),
        gate("validation_recall_at_1_lower_95", validation["recall_at_1_lower_95"] >= 0.85, f'{validation["recall_at_1_lower_95"]:.3f}', ">= 0.850"),
        gate("validation_recall_at_3_lower_95", validation["recall_at_3_lower_95"] >= 0.90, f'{validation["recall_at_3_lower_95"]:.3f}', ">= 0.900"),
        gate("validation_abstention_lower_95", validation["unsupported_abstention_lower_95"] >= 0.95, f'{validation["unsupported_abstention_lower_95"]:.3f}', ">= 0.950"),
        gate("development_validation_recall_at_1_gap", abs(development["recall_at_1"] - validation["recall_at_1"]) <= 0.05, f'{abs(development["recall_at_1"] - validation["recall_at_1"]):.3f}', "<= 0.050"),
        gate("development_validation_recall_at_3_gap", abs(development["recall_at_3"] - validation["recall_at_3"]) <= 0.05, f'{abs(development["recall_at_3"] - validation["recall_at_3"]):.3f}', "<= 0.050"),
        gate("citation_groundedness_review", manifest.get("citation_review_status") == "human_reviewed", manifest.get("citation_review_status", "missing"), "human_reviewed"),
        gate("locked_test_evaluated", args.include_locked_test, args.include_locked_test, "true on the one-time release run"),
    ]
    if args.include_locked_test:
        locked = metrics["locked_test"]
        gates.extend(
            [
                gate("locked_supported_sample_size", locked["supported_count"] >= 200, locked["supported_count"], ">= 200"),
                gate("locked_unsupported_sample_size", locked["unsupported_count"] >= 100, locked["unsupported_count"], ">= 100"),
                gate("locked_recall_at_1_lower_95", locked["recall_at_1_lower_95"] >= 0.85, f'{locked["recall_at_1_lower_95"]:.3f}', ">= 0.850"),
                gate("locked_recall_at_3_lower_95", locked["recall_at_3_lower_95"] >= 0.90, f'{locked["recall_at_3_lower_95"]:.3f}', ">= 0.900"),
                gate("locked_abstention_lower_95", locked["unsupported_abstention_lower_95"] >= 0.95, f'{locked["unsupported_abstention_lower_95"]:.3f}', ">= 0.950"),
            ]
        )

    payload = {
        "ready": all(item["passed"] for item in gates),
        "product": "kubernetes_evidence_copilot",
        "metrics": metrics,
        "gates": gates,
        "locked_test_evaluated": args.include_locked_test,
    }
    print(json.dumps(payload, indent=2))
    raise SystemExit(0 if payload["ready"] else 1)


if __name__ == "__main__":
    main()
