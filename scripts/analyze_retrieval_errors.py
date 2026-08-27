#!/usr/bin/env python3
"""Analyze retrieval failures without opening validation or locked-test data."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from support_copilot.evaluation import EvaluationCase, load_cases
from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.models import KnowledgeDocument, SearchResult


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "real_benchmark"
ALLOWED_SPLITS = ("development", "challenge")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_rank(
    expected_document_id: str,
    results: list[SearchResult],
) -> int | None:
    return next(
        (
            index
            for index, result in enumerate(results, start=1)
            if result.document_id == expected_document_id
        ),
        None,
    )


def classify_case(case: EvaluationCase, results: list[SearchResult]) -> str:
    confident = retrieval_is_confident(results[:2])
    if case.expected_document_id is None:
        return "unsupported_false_accept" if confident else "correct_abstention"

    rank = expected_rank(case.expected_document_id, results)
    if rank == 1 and confident:
        return "correct_supported"
    if rank == 1:
        return "confidence_gate_false_reject"
    if rank is not None and rank <= 3 and confident:
        return "ranking_error_top3"
    if rank is not None and rank <= 3:
        return "ranking_and_confidence_failure"
    if rank is not None:
        return "deep_ranking_failure"
    return "lexical_retrieval_miss"


def analyze_split(split: str) -> dict:
    if split not in ALLOWED_SPLITS:
        raise ValueError(f"analysis split must be one of {ALLOWED_SPLITS}")
    case_name = "challenge_judged" if split == "challenge" else split
    case_path = BENCHMARK / f"{case_name}.json"
    knowledge_path = BENCHMARK / f"{split}_knowledge.json"
    cases = load_cases(case_path)
    documents = [
        KnowledgeDocument(**item)
        for item in json.loads(knowledge_path.read_text(encoding="utf-8"))
    ]
    knowledge_base = KnowledgeBase(documents)
    records = []
    counts: collections.Counter[str] = collections.Counter()

    for case in cases:
        results = knowledge_base.search(case.question, limit=20)
        category = classify_case(case, results)
        counts[category] += 1
        if category in {"correct_supported", "correct_abstention"}:
            continue
        rank = (
            expected_rank(case.expected_document_id, results)
            if case.expected_document_id
            else None
        )
        records.append(
            {
                "case_id": case.case_id,
                "source_conversation_id": case.source_conversation_id,
                "source_tweet_id": case.source_tweet_id,
                "question": case.question,
                "expected_document_id": case.expected_document_id,
                "failure_category": category,
                "expected_rank_within_20": rank,
                "retrieval_confident": retrieval_is_confident(results[:2]),
                "top_candidates": [
                    {
                        "document_id": result.document_id,
                        "score": result.score,
                        "title": result.title,
                    }
                    for result in results[:3]
                ],
                "label_governance_warning": (
                    "blanket-approved unsupported challenge label"
                    if split == "challenge"
                    and case.expected_document_id is None
                    and case.adjudication
                    and "Blanket-approved" in case.adjudication.get("review_notes", "")
                    else None
                ),
            }
        )

    return {
        "case_count": len(cases),
        "supported_count": sum(case.expected_document_id is not None for case in cases),
        "unsupported_count": sum(case.expected_document_id is None for case in cases),
        "failure_counts": dict(sorted(counts.items())),
        "case_sha256": sha256(case_path),
        "knowledge_sha256": sha256(knowledge_path),
        "failures": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze development and challenge retrieval without validation/test access."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "real_retrieval_error_analysis.json",
    )
    args = parser.parse_args()
    payload = {
        "retriever": "bm25_v1",
        "minimum_score": 9.0,
        "minimum_score_ratio": 1.1,
        "analyzed_splits": list(ALLOWED_SPLITS),
        "excluded_splits": ["validation", "test"],
        "splits": {split: analyze_split(split) for split in ALLOWED_SPLITS},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary = {
        split: result["failure_counts"]
        for split, result in payload["splits"].items()
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
