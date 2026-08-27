#!/usr/bin/env python3
"""Print the reproducible retrieval baseline for the support-copilot MVP."""

import argparse
import hashlib
import json
from pathlib import Path

from support_copilot.evaluation import (
    load_cases,
    retrieval_recall_at_k,
    selective_risk_curve,
    unsupported_abstention_rate,
    wilson_interval,
)
from support_copilot.knowledge import (
    DEFAULT_MINIMUM_SCORE,
    DEFAULT_MINIMUM_SCORE_RATIO,
    KnowledgeBase,
)
from support_copilot.models import KnowledgeDocument


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data"
MINIMUM_RETRIEVAL_SCORE = DEFAULT_MINIMUM_SCORE
MINIMUM_SCORE_RATIO = DEFAULT_MINIMUM_SCORE_RATIO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", choices=("synthetic", "real"), default="synthetic")
    parser.add_argument(
        "--split",
        choices=("train", "validation", "challenge", "test"),
        default="validation",
    )
    args = parser.parse_args()
    if args.benchmark == "real":
        benchmark_directory = DATA_DIRECTORY / "real_benchmark"
        manifest = json.loads((benchmark_directory / "manifest.json").read_text())
        split_name = "development" if args.split == "train" else args.split
        if split_name == "test":
            if manifest.get("test_review_status") not in {"sampled_human_review", "human_reviewed"}:
                raise SystemExit("real benchmark has not completed review")
            knowledge_path = benchmark_directory / "knowledge.json"
            checksum_fields = ("test_sha256", "knowledge_sha256")
        elif split_name == "challenge":
            if manifest.get("challenge_review_status") not in {
                "human_adjudicated",
                "user_blanket_approved",
            }:
                raise SystemExit("challenge labels must be adjudicated before evaluation")
            if manifest["challenge_review_status"] == "user_blanket_approved":
                print(
                    "warning: challenge labels were blanket-approved, not case-by-case adjudicated"
                )
            knowledge_path = benchmark_directory / "challenge_knowledge.json"
            checksum_fields = (
                "challenge_judged_sha256",
                "challenge_knowledge_sha256",
            )
        else:
            knowledge_path = benchmark_directory / f"{split_name}_knowledge.json"
            checksum_fields = (
                f"{split_name}_sha256",
                f"{split_name}_knowledge_sha256",
            )
        split_path = benchmark_directory / (
            "challenge_judged.json" if split_name == "challenge" else f"{split_name}.json"
        )
        for path, checksum_field in (
            (split_path, checksum_fields[0]),
            (knowledge_path, checksum_fields[1]),
        ):
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if checksum != manifest[checksum_field]:
                raise SystemExit(f"locked real benchmark checksum mismatch: {path.name}")
        report_name = (
            "real_challenge_judged" if split_name == "challenge" else f"real_{split_name}"
        )
    else:
        if args.split == "challenge":
            raise SystemExit("challenge split is available only for the real benchmark")
        knowledge_path = DATA_DIRECTORY / "policies.json"
        split_path = DATA_DIRECTORY / "splits" / f"{args.split}.json"
        if args.split == "test":
            manifest = json.loads((DATA_DIRECTORY / "dataset_manifest.json").read_text())
            checksum = hashlib.sha256(split_path.read_bytes()).hexdigest()
            if checksum != manifest["test_sha256"]:
                raise SystemExit("locked test checksum mismatch")
        report_name = args.split

    document_payload = json.loads(
        knowledge_path.read_text(encoding="utf-8")
    )
    documents = [KnowledgeDocument(**item) for item in document_payload]
    cases = load_cases(split_path)
    knowledge_base = KnowledgeBase(documents)

    for k in (1, 3):
        recall = retrieval_recall_at_k(
            knowledge_base,
            cases,
            k=k,
            minimum_score=MINIMUM_RETRIEVAL_SCORE,
            minimum_score_ratio=MINIMUM_SCORE_RATIO,
        )
        print(f"{report_name}_retrieval_recall_at_{k}={recall:.3f}")
        supported_count = sum(case.expected_document_id is not None for case in cases)
        lower, upper = wilson_interval(round(recall * supported_count), supported_count)
        print(f"{report_name}_retrieval_recall_at_{k}_95ci=[{lower:.3f},{upper:.3f}]")
    abstention = unsupported_abstention_rate(
        knowledge_base,
        cases,
        minimum_score=MINIMUM_RETRIEVAL_SCORE,
        minimum_score_ratio=MINIMUM_SCORE_RATIO,
    )
    print(f"{report_name}_unsupported_abstention_rate={abstention:.3f}")
    unsupported_count = sum(case.expected_document_id is None for case in cases)
    lower, upper = wilson_interval(round(abstention * unsupported_count), unsupported_count)
    print(f"{report_name}_unsupported_abstention_rate_95ci=[{lower:.3f},{upper:.3f}]")
    for point in selective_risk_curve(
        knowledge_base,
        cases,
        minimum_scores=(5.0, 7.0, 9.0, 12.0, 15.0),
        minimum_score_ratio=MINIMUM_SCORE_RATIO,
    ):
        print(
            f"{report_name}_selective_score_{point.minimum_score:g}="
            f"coverage:{point.coverage:.3f},risk:{point.risk:.3f}"
        )


if __name__ == "__main__":
    main()
