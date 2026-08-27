#!/usr/bin/env python3
"""Calibrate the lexical confidence gate on development data only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from support_copilot.evaluation import EvaluationCase, load_cases
from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.models import KnowledgeDocument, SearchResult


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "real_benchmark"
DIAGNOSTIC_OVERLAY = (
    ROOT / "artifacts" / "retrieval_diagnostic_audit_overlay_20260825.json"
)
BASELINE_MINIMUM_SCORE = 9.0
BASELINE_MINIMUM_SCORE_RATIO = 1.1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_documents(path: Path) -> list[KnowledgeDocument]:
    return [
        KnowledgeDocument(**row)
        for row in json.loads(path.read_text(encoding="utf-8"))
    ]


def measure(
    cases: list[EvaluationCase],
    ranked: list[list[SearchResult]],
    minimum_score: float,
    minimum_score_ratio: float,
) -> dict[str, float]:
    supported = [
        index
        for index, case in enumerate(cases)
        if case.expected_document_id is not None
    ]
    unsupported = [
        index
        for index, case in enumerate(cases)
        if case.expected_document_id is None
    ]
    accepted = [
        retrieval_is_confident(results, minimum_score, minimum_score_ratio)
        for results in ranked
    ]
    recall_at_1 = sum(
        accepted[index]
        and ranked[index][0].document_id == cases[index].expected_document_id
        for index in supported
    ) / len(supported)
    recall_at_3 = sum(
        accepted[index]
        and any(
            result.document_id == cases[index].expected_document_id
            for result in ranked[index][:3]
        )
        for index in supported
    ) / len(supported)
    unsupported_abstention = sum(
        not accepted[index] for index in unsupported
    ) / len(unsupported)
    return {
        "recall_at_1": recall_at_1,
        "recall_at_3": recall_at_3,
        "unsupported_abstention": unsupported_abstention,
        "coverage": sum(accepted) / len(cases),
    }


def candidate_grid() -> list[tuple[float, float]]:
    return [
        (score_step / 2, ratio_step / 20)
        for score_step in range(10, 41)
        for ratio_step in range(20, 41)
    ]


def select_candidate(
    candidates: list[dict[str, float]],
    baseline: dict[str, float],
) -> dict[str, float]:
    feasible = [
        candidate
        for candidate in candidates
        if candidate["recall_at_1"] >= baseline["recall_at_1"]
        and candidate["recall_at_3"] >= baseline["recall_at_3"]
    ]
    if not feasible:
        raise ValueError("no candidate preserves baseline development recall")
    return sorted(
        feasible,
        key=lambda candidate: (
            -candidate["unsupported_abstention"],
            -candidate["recall_at_1"],
            -candidate["recall_at_3"],
            -candidate["diagnostic_false_accept_abstention"],
            candidate["minimum_score"],
            candidate["minimum_score_ratio"],
        ),
    )[0]


def calibrate() -> dict:
    development_path = BENCHMARK / "development.json"
    development_knowledge_path = BENCHMARK / "development_knowledge.json"
    challenge_knowledge_path = BENCHMARK / "challenge_knowledge.json"
    cases = load_cases(development_path)
    development_kb = KnowledgeBase(load_documents(development_knowledge_path))
    ranked = [development_kb.search(case.question, limit=3) for case in cases]

    overlay = json.loads(DIAGNOSTIC_OVERLAY.read_text(encoding="utf-8"))
    if overlay.get("benchmark_mutation_authorized") is not False:
        raise ValueError("diagnostic overlay must not authorize benchmark mutation")
    false_accept_questions = [
        row["question"]
        for row in overlay["decisions"]
        if row["reviewer_decision"] == "unsupported"
    ]
    challenge_kb = KnowledgeBase(load_documents(challenge_knowledge_path))
    false_accept_ranked = [
        challenge_kb.search(question, limit=3)
        for question in false_accept_questions
    ]

    baseline = {
        "minimum_score": BASELINE_MINIMUM_SCORE,
        "minimum_score_ratio": BASELINE_MINIMUM_SCORE_RATIO,
        **measure(
            cases,
            ranked,
            BASELINE_MINIMUM_SCORE,
            BASELINE_MINIMUM_SCORE_RATIO,
        ),
    }
    candidates = []
    for minimum_score, minimum_score_ratio in candidate_grid():
        candidate = {
            "minimum_score": minimum_score,
            "minimum_score_ratio": minimum_score_ratio,
            **measure(
                cases,
                ranked,
                minimum_score,
                minimum_score_ratio,
            ),
        }
        candidate["diagnostic_false_accept_abstention"] = sum(
            not retrieval_is_confident(
                results, minimum_score, minimum_score_ratio
            )
            for results in false_accept_ranked
        ) / len(false_accept_ranked)
        candidates.append(candidate)

    selected = select_candidate(candidates, baseline)
    return {
        "candidate": "bm25_v2_confidence",
        "development_selection_status": "selected_for_independent_validation",
        "calibration_scope": (
            "real development plus diagnostic challenge regressions"
        ),
        "selection_rule": (
            "preserve development Recall@1 and Recall@3, then maximize "
            "development unsupported abstention"
        ),
        "protected_splits_evaluated": [],
        "test_set_rerun": False,
        "development_case_count": len(cases),
        "diagnostic_false_accept_count": len(false_accept_questions),
        "development_sha256": sha256(development_path),
        "development_knowledge_sha256": sha256(development_knowledge_path),
        "diagnostic_overlay_sha256": sha256(DIAGNOSTIC_OVERLAY),
        "baseline": baseline,
        "selected": selected,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "calibration_results.json",
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    payload = calibrate()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output}")
    print(rendered, end="")


if __name__ == "__main__":
    main()
