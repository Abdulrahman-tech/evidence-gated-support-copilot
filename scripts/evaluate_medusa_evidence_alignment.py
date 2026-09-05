#!/usr/bin/env python3
"""Evaluate a deterministic evidence-alignment gate on Medusa development."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
from pathlib import Path

from support_copilot.evaluation import (
    EvaluationCase,
    load_cases,
    retrieval_confidence_metrics,
)
from support_copilot.knowledge import (
    DEFAULT_MINIMUM_SCORE,
    DEFAULT_MINIMUM_SCORE_RATIO,
    KnowledgeBase,
    tokenize,
)
from support_copilot.models import KnowledgeDocument, SearchResult
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
SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def document_frequency(
    documents: list[KnowledgeDocument],
) -> collections.Counter[str]:
    frequencies: collections.Counter[str] = collections.Counter()
    for document in documents:
        frequencies.update(set(tokenize(f"{document.title} {document.text}")))
    return frequencies


def weighted_coverage(
    query_terms: set[str],
    evidence_terms: set[str],
    frequencies: collections.Counter[str],
    document_count: int,
) -> float:
    if not query_terms:
        return 0.0

    def weight(term: str) -> float:
        frequency = frequencies[term]
        return math.log(
            1 + (document_count - frequency + 0.5) / (frequency + 0.5)
        )

    denominator = sum(weight(term) for term in query_terms)
    return sum(weight(term) for term in query_terms & evidence_terms) / denominator


def alignment_features(
    question: str,
    results: list[SearchResult],
    frequencies: collections.Counter[str],
    document_count: int,
) -> tuple[float, float]:
    if ". Source context:" in question:
        title, _ = question.split(". Source context:", 1)
    else:
        title = question.splitlines()[0]
    title_terms = set(tokenize(title))
    question_terms = set(tokenize(question))
    sentence_terms = [
        terms
        for result in results
        for sentence in SENTENCE_BOUNDARY.split(f"{result.title}. {result.passage}")
        if (terms := set(tokenize(sentence)))
    ]
    if not sentence_terms or not title_terms or not question_terms:
        return 0.0, 0.0
    title_alignment = max(
        len(title_terms & terms) / len(title_terms) for terms in sentence_terms
    )
    evidence_alignment = max(
        weighted_coverage(question_terms, terms, frequencies, document_count)
        for terms in sentence_terms
    )
    return title_alignment, evidence_alignment


def measure_alignment(
    cases: list[EvaluationCase],
    ranked: list[list[SearchResult]],
    features: list[tuple[float, float]],
    minimum_title_alignment: float,
    minimum_evidence_alignment: float,
) -> dict[str, float | int]:
    supported_count = sum(case.expected_document_id is not None for case in cases)
    unsupported_count = len(cases) - supported_count
    accepted = [
        title_alignment >= minimum_title_alignment
        and evidence_alignment >= minimum_evidence_alignment
        for title_alignment, evidence_alignment in features
    ]
    supported_hits_at_1 = sum(
        is_accepted
        and results
        and results[0].document_id == case.expected_document_id
        for case, results, is_accepted in zip(cases, ranked, accepted)
        if case.expected_document_id is not None
    )
    supported_hits_at_3 = sum(
        is_accepted
        and any(
            result.document_id == case.expected_document_id
            for result in results[:3]
        )
        for case, results, is_accepted in zip(cases, ranked, accepted)
        if case.expected_document_id is not None
    )
    unsupported_abstentions = sum(
        not is_accepted
        for case, is_accepted in zip(cases, accepted)
        if case.expected_document_id is None
    )
    return {
        "minimum_title_alignment": minimum_title_alignment,
        "minimum_evidence_alignment": minimum_evidence_alignment,
        "supported_recall_at_1": supported_hits_at_1 / supported_count,
        "supported_recall_at_3": supported_hits_at_3 / supported_count,
        "unsupported_abstention": unsupported_abstentions / unsupported_count,
        "accepted_count": sum(accepted),
        "unsupported_pass_count": unsupported_count - unsupported_abstentions,
    }


def evaluate() -> dict:
    development_path = BENCHMARK / "development.json"
    validation_path = BENCHMARK / "validation.json"
    locked_test_path = BENCHMARK / "test.json"
    knowledge_path = MEDUSA / "knowledge_expanded.json"
    benchmark_manifest = json.loads((BENCHMARK / "manifest.json").read_text())
    knowledge_manifest = json.loads((MEDUSA / "expanded_manifest.json").read_text())
    checksums = {
        "development": sha256(development_path),
        "validation": sha256(validation_path),
        "locked_test": sha256(locked_test_path),
        "knowledge": sha256(knowledge_path),
    }
    if checksums["development"] != benchmark_manifest["splits"]["development"]["sha256"]:
        raise ValueError("Medusa development checksum mismatch")
    if checksums["validation"] != EXPECTED_VALIDATION_SHA256:
        raise ValueError("protected validation split changed")
    if checksums["locked_test"] != EXPECTED_LOCKED_TEST_SHA256:
        raise ValueError("protected locked test changed")
    if checksums["knowledge"] != knowledge_manifest["knowledge_sha256"]:
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
    frequencies = document_frequency(documents)
    features = [
        alignment_features(case.question, results, frequencies, len(documents))
        for case, results in zip(cases, ranked)
    ]
    title_thresholds = sorted({0.0} | {feature[0] for feature in features})
    evidence_thresholds = sorted({0.0} | {feature[1] for feature in features})
    candidates = [
        measure_alignment(cases, ranked, features, title, evidence)
        for title in title_thresholds
        for evidence in evidence_thresholds
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
    recall_preserving = [
        candidate
        for candidate in candidates
        if candidate["supported_recall_at_3"] >= MINIMUM_SUPPORTED_RECALL_AT_3
    ]
    best_recall_preserving = max(
        recall_preserving,
        key=lambda candidate: (
            candidate["unsupported_abstention"],
            candidate["supported_recall_at_1"],
            -candidate["accepted_count"],
        ),
    )
    baseline = retrieval_confidence_metrics(
        cases,
        ranked,
        DEFAULT_MINIMUM_SCORE,
        DEFAULT_MINIMUM_SCORE_RATIO,
    )
    score_thresholds = sorted(
        {0.0, DEFAULT_MINIMUM_SCORE}
        | {results[0].score for results in ranked if results}
    )
    ratio_thresholds = sorted(
        {1.0, DEFAULT_MINIMUM_SCORE_RATIO}
        | {
            results[0].score / results[1].score
            for results in ranked
            if len(results) > 1
        }
    )
    score_ratio_candidates = [
        retrieval_confidence_metrics(cases, ranked, score, ratio)
        for score in score_thresholds
        for ratio in ratio_thresholds
    ]
    best_recall_preserving_score_ratio = max(
        (
            candidate
            for candidate in score_ratio_candidates
            if candidate["supported_recall_at_3"] >= MINIMUM_SUPPORTED_RECALL_AT_3
        ),
        key=lambda candidate: (
            candidate["unsupported_abstention"],
            candidate["supported_recall_at_1"],
            -candidate["accepted_count"],
        ),
    )

    return {
        "candidate": "sentence_evidence_alignment_v1",
        "calibration_scope": "medusa_development_only",
        "candidate_status": "qualified" if feasible else "rejected",
        "selection": selected,
        "runtime_changed": False,
        "rejection_reason": (
            None
            if feasible
            else "No alignment threshold meets both development recall and abstention requirements."
        ),
        "requirements": {
            "minimum_supported_recall_at_3": MINIMUM_SUPPORTED_RECALL_AT_3,
            "minimum_unsupported_abstention": MINIMUM_UNSUPPORTED_ABSTENTION,
        },
        "development": {
            "case_count": len(cases),
            "supported_count": sum(
                case.expected_document_id is not None for case in cases
            ),
            "unsupported_count": sum(
                case.expected_document_id is None for case in cases
            ),
            "sha256": checksums["development"],
        },
        "score_ratio_baseline": baseline,
        "best_recall_preserving_score_ratio": best_recall_preserving_score_ratio,
        "best_recall_preserving_alignment": best_recall_preserving,
        "unsupported_abstention_improvement": (
            best_recall_preserving["unsupported_abstention"]
            - best_recall_preserving_score_ratio["unsupported_abstention"]
        ),
        "candidate_threshold_count": len(candidates),
        "knowledge_sha256": checksums["knowledge"],
        "protected_splits_evaluated": [],
        "protected_split_checksums": {
            "validation": checksums["validation"],
            "locked_test": checksums["locked_test"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "medusa_evidence_alignment_candidate.json",
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(evaluate(), indent=2, sort_keys=True) + "\n"
    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output}")
    print(rendered, end="")


if __name__ == "__main__":
    main()
