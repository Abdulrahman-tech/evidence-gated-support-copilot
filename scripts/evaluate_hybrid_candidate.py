#!/usr/bin/env python3
"""Evaluate the local hybrid candidate without exposing the locked final test."""

import argparse
import hashlib
import json
from pathlib import Path

from support_copilot.evaluation import load_cases, wilson_interval
from support_copilot.hybrid import HybridKnowledgeBase
from support_copilot.models import KnowledgeDocument


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "real_benchmark"


def evaluate(
    split: str,
    rank_constant: int,
    semantic_weight: float,
) -> None:
    manifest = json.loads((BENCHMARK / "manifest.json").read_text(encoding="utf-8"))
    if split == "challenge":
        case_path = BENCHMARK / "challenge_judged.json"
        case_checksum = "challenge_judged_sha256"
        if manifest.get("challenge_review_status") not in {
            "human_adjudicated",
            "user_blanket_approved",
        }:
            raise SystemExit("challenge labels must be reviewed before evaluation")
        if manifest["challenge_review_status"] == "user_blanket_approved":
            print("warning: challenge labels were blanket-approved, not adjudicated")
    else:
        case_path = BENCHMARK / f"{split}.json"
        case_checksum = f"{split}_sha256"
    knowledge_path = BENCHMARK / f"{split}_knowledge.json"
    for path, checksum_field in (
        (case_path, case_checksum),
        (knowledge_path, f"{split}_knowledge_sha256"),
    ):
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[checksum_field]:
            raise SystemExit(f"benchmark checksum mismatch: {path.name}")

    documents = [
        KnowledgeDocument(**item)
        for item in json.loads(knowledge_path.read_text(encoding="utf-8"))
    ]
    cases = load_cases(case_path)
    knowledge_base = HybridKnowledgeBase(
        documents,
        rank_constant=rank_constant,
        semantic_weight=semantic_weight,
    )
    retrievals = [knowledge_base.retrieve(case.question, limit=3) for case in cases]

    supported = [
        (case, retrieval)
        for case, retrieval in zip(cases, retrievals)
        if case.expected_document_id is not None
    ]
    unsupported = [
        retrieval
        for case, retrieval in zip(cases, retrievals)
        if case.expected_document_id is None
    ]
    for k in (1, 3):
        hits = sum(
            retrieval.lexical_confident
            and any(
                result.document_id == case.expected_document_id
                for result in retrieval.results[:k]
            )
            for case, retrieval in supported
        )
        rate = hits / len(supported)
        lower, upper = wilson_interval(hits, len(supported))
        print(f"hybrid_{split}_retrieval_recall_at_{k}={rate:.3f}")
        print(f"hybrid_{split}_retrieval_recall_at_{k}_95ci=[{lower:.3f},{upper:.3f}]")
    abstentions = sum(not retrieval.lexical_confident for retrieval in unsupported)
    rate = abstentions / len(unsupported)
    lower, upper = wilson_interval(abstentions, len(unsupported))
    print(f"hybrid_{split}_unsupported_abstention_rate={rate:.3f}")
    print(f"hybrid_{split}_unsupported_abstention_rate_95ci=[{lower:.3f},{upper:.3f}]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split",
        choices=("development", "validation", "challenge", "all"),
        default="validation",
    )
    parser.add_argument(
        "--candidate",
        choices=("v1", "v2"),
        default="v1",
    )
    args = parser.parse_args()
    rank_constant, semantic_weight = (
        (60, 1.0) if args.candidate == "v1" else (0, 0.75)
    )
    splits = (
        ("development", "validation", "challenge")
        if args.split == "all"
        else (args.split,)
    )
    for split in splits:
        evaluate(split, rank_constant, semantic_weight)


if __name__ == "__main__":
    main()
