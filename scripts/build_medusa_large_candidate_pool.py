#!/usr/bin/env python3
"""Build a clean, non-labelled Medusa support candidate pool."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

from support_copilot.medusa_discussions import near_duplicate


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "medusa" / "benchmark"
SEED = "medusa-large-candidate-pool-v1"
AUTOMATION = re.compile(r"^(?:chore|build|ci|release|deps?|bump|changeset)(?:\W|$)", re.I)
QUESTION_PREFIX = re.compile(r"^(?:how|why|when|where|what|can|cannot|can't|is|are|does|do)\b", re.I)
AREA_PATTERNS = (
    ("auth", re.compile(r"\b(auth|oauth|login|password|session|token)\b", re.I)),
    ("payment", re.compile(r"\b(payment|refund|capture|stripe|paypal|authorization)\b", re.I)),
    ("order", re.compile(r"\b(order|return|exchange|claim|draft order)\b", re.I)),
    ("cart", re.compile(r"\b(cart|line item|checkout)\b", re.I)),
    ("product", re.compile(r"\b(product|variant|collection|category|tag)\b", re.I)),
    ("pricing", re.compile(r"\b(price|pricing|price list|currency)\b", re.I)),
    ("promotion", re.compile(r"\b(promotion|discount|coupon|buy.get)\b", re.I)),
    ("inventory", re.compile(r"\b(inventory|reservation|stock|location)\b", re.I)),
    ("fulfillment", re.compile(r"\b(fulfillment|shipping|delivery)\b", re.I)),
    ("customer", re.compile(r"\b(customer|guest)\b", re.I)),
    ("admin", re.compile(r"\b(admin|dashboard)\b", re.I)),
    ("deployment", re.compile(r"\b(deploy|docker|server|worker|production|build)\b", re.I)),
    ("plugins", re.compile(r"\b(plugin|extension)\b", re.I)),
    ("api", re.compile(r"\b(api|sdk|graphql|endpoint|query)\b", re.I)),
    ("database", re.compile(r"\b(database|postgres|migration|schema|redis)\b", re.I)),
    ("observability", re.compile(r"\b(opentelemetry|telemetry|trace|metric|log)\b", re.I)),
    ("localization", re.compile(r"\b(locale|translation|language|country)\b", re.I)),
)


def benchmark_urls() -> set[str]:
    urls = set()
    for path in BENCHMARK.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            urls.update(item.get("source_url", "") for item in payload)
    reviewed_discussions = ROOT / "data" / "medusa" / "discussion_sources.json"
    if reviewed_discussions.exists():
        urls.update(
            item["source_url"]
            for item in json.loads(reviewed_discussions.read_text(encoding="utf-8"))
        )
    return urls


def area(question: str) -> str:
    return next(
        (name for name, pattern in AREA_PATTERNS if pattern.search(question)),
        "other",
    )


def intent(item: dict) -> str:
    labels = {label.lower() for label in item.get("source_labels", [])}
    if "type: docs" in labels:
        return "documentation_gap"
    if "type: bug" in labels or "bug" in labels:
        return "bug_report"
    if QUESTION_PREFIX.search(item["question"]):
        return "support_question"
    return "technical_request"


def rank_key(item: dict) -> str:
    return hashlib.sha256(f"{SEED}:{item['case_id']}".encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--discussions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", type=int, default=1_000)
    args = parser.parse_args()
    if args.target <= 0:
        raise ValueError("target must be positive")

    sources = json.loads(args.issues.read_text(encoding="utf-8"))
    if args.discussions:
        sources.extend(json.loads(args.discussions.read_text(encoding="utf-8")))
    locked_urls = benchmark_urls()
    excluded = collections.Counter()
    cleaned = []
    for item in sources:
        labels = {label.lower() for label in item.get("source_labels", [])}
        if item["source_url"] in locked_urls:
            excluded["existing_benchmark_source"] += 1
            continue
        if item.get("body_word_count", 10) < 10:
            excluded["insufficient_source_context"] += 1
            continue
        if "type: chore" in labels or AUTOMATION.search(item["question"]):
            excluded["automation_or_maintenance"] += 1
            continue
        if any(near_duplicate(item["question"], existing["question"], 0.82) for existing in cleaned):
            excluded["near_duplicate"] += 1
            continue
        cleaned.append(
            {
                **item,
                "source_type": item.get("source_type", "github_discussion_answered_q_and_a"),
                "proposed_product_area": area(item["question"]),
                "support_intent": intent(item),
                "label_status": "unlabelled_candidate",
            }
        )

    grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for item in cleaned:
        grouped[item["proposed_product_area"]].append(item)
    for items in grouped.values():
        items.sort(key=rank_key)

    selected = []
    area_names = sorted(grouped)
    position = 0
    while len(selected) < args.target:
        added = False
        for name in area_names:
            if position < len(grouped[name]):
                selected.append(grouped[name][position])
                added = True
                if len(selected) == args.target:
                    break
        if not added:
            break
        position += 1
    if len(selected) < args.target:
        raise ValueError(
            f"only {len(selected)} clean candidates remain; target is {args.target}"
        )

    cluster_representatives: list[dict] = []
    for item in selected:
        representative = next(
            (
                candidate
                for candidate in cluster_representatives
                if near_duplicate(item["question"], candidate["question"], 0.6)
            ),
            None,
        )
        if representative is None:
            representative = item
            cluster_representatives.append(item)
        item["leakage_group_id"] = "topic-" + hashlib.sha256(
            representative["case_id"].encode()
        ).hexdigest()[:12]

    selected.sort(key=lambda item: item["case_id"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_bytes = (json.dumps(selected, indent=2, sort_keys=True) + "\n").encode()
    args.output.write_bytes(output_bytes)
    manifest = {
        "seed": SEED,
        "target_count": args.target,
        "input_count": len(sources),
        "clean_count_before_sampling": len(cleaned),
        "output_count": len(selected),
        "excluded": dict(sorted(excluded.items())),
        "source_type_counts": dict(sorted(collections.Counter(item["source_type"] for item in selected).items())),
        "product_area_counts": dict(sorted(collections.Counter(item["proposed_product_area"] for item in selected).items())),
        "support_intent_counts": dict(sorted(collections.Counter(item["support_intent"] for item in selected).items())),
        "leakage_group_count": len({item["leakage_group_id"] for item in selected}),
        "sha256": hashlib.sha256(output_bytes).hexdigest(),
        "label_policy": "Authentic public candidates only; no evaluation label or retriever prediction is included.",
    }
    (args.output.parent / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
