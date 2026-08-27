#!/usr/bin/env python3
"""Evaluate Medusa development and validation without opening the locked test."""

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
DATA_DIRECTORY = PROJECT_ROOT / "data" / "medusa"
BENCHMARK_DIRECTORY = DATA_DIRECTORY / "benchmark"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_split(knowledge_base: KnowledgeBase, split_name: str) -> None:
    split_path = BENCHMARK_DIRECTORY / f"{split_name}.json"
    cases = load_cases(split_path)
    supported_count = sum(case.expected_document_id is not None for case in cases)
    unsupported_count = len(cases) - supported_count

    print(
        f"medusa_{split_name}_cases={len(cases)} "
        f"(supported={supported_count},unsupported={unsupported_count})"
    )
    for k in (1, 3):
        recall = retrieval_recall_at_k(
            knowledge_base,
            cases,
            k=k,
            minimum_score=DEFAULT_MINIMUM_SCORE,
            minimum_score_ratio=DEFAULT_MINIMUM_SCORE_RATIO,
        )
        lower, upper = wilson_interval(round(recall * supported_count), supported_count)
        print(f"medusa_{split_name}_retrieval_recall_at_{k}={recall:.3f}")
        print(
            f"medusa_{split_name}_retrieval_recall_at_{k}_95ci="
            f"[{lower:.3f},{upper:.3f}]"
        )

    abstention = unsupported_abstention_rate(
        knowledge_base,
        cases,
        minimum_score=DEFAULT_MINIMUM_SCORE,
        minimum_score_ratio=DEFAULT_MINIMUM_SCORE_RATIO,
    )
    lower, upper = wilson_interval(round(abstention * unsupported_count), unsupported_count)
    print(f"medusa_{split_name}_unsupported_abstention_rate={abstention:.3f}")
    print(
        f"medusa_{split_name}_unsupported_abstention_rate_95ci="
        f"[{lower:.3f},{upper:.3f}]"
    )
    for point in selective_risk_curve(
        knowledge_base,
        cases,
        minimum_scores=(5.0, 7.0, 9.0, 12.0, 15.0),
        minimum_score_ratio=DEFAULT_MINIMUM_SCORE_RATIO,
    ):
        print(
            f"medusa_{split_name}_selective_score_{point.minimum_score:g}="
            f"coverage:{point.coverage:.3f},risk:{point.risk:.3f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split",
        choices=("development", "validation", "all"),
        default="all",
        help="The locked test is deliberately unavailable from this command.",
    )
    args = parser.parse_args()

    benchmark_manifest = json.loads(
        (BENCHMARK_DIRECTORY / "manifest.json").read_text(encoding="utf-8")
    )
    knowledge_manifest = json.loads(
        (DATA_DIRECTORY / "expanded_manifest.json").read_text(encoding="utf-8")
    )
    knowledge_path = DATA_DIRECTORY / "knowledge_expanded.json"
    if sha256(knowledge_path) != knowledge_manifest["knowledge_sha256"]:
        raise SystemExit("Medusa knowledge checksum mismatch")

    split_names = (
        ("development", "validation") if args.split == "all" else (args.split,)
    )
    for split_name in split_names:
        split_path = BENCHMARK_DIRECTORY / f"{split_name}.json"
        if sha256(split_path) != benchmark_manifest["splits"][split_name]["sha256"]:
            raise SystemExit(f"Medusa {split_name} checksum mismatch")

    documents = [
        KnowledgeDocument(**item)
        for item in json.loads(knowledge_path.read_text(encoding="utf-8"))
    ]
    knowledge_base = KnowledgeBase(documents)
    for split_name in split_names:
        evaluate_split(knowledge_base, split_name)


if __name__ == "__main__":
    main()
