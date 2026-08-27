#!/usr/bin/env python3
"""Build leakage-safe real development and validation retrieval sets."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from build_real_benchmark import OUTPUT, encoded, load_candidates


ROOT = Path(__file__).resolve().parents[1]
SPLIT_SIZES = {
    "development": (80, 20),
    "validation": (80, 20),
    "challenge": (80, 100),
}


def stable_key(conversation_id: str) -> str:
    return hashlib.sha256(f"real-development-validation-v1:{conversation_id}".encode()).hexdigest()


def build_split(
    selected: list[tuple], name: str, supported_count: int
) -> tuple[list[dict], list[dict]]:
    supported = selected[:supported_count]
    unsupported = selected[supported_count:]
    knowledge = []
    cases = []
    for entry, first_tweet, question, resolution in supported:
        conversation_id = entry["conversation_id"]
        document_id = "tweetsumm-" + conversation_id[:12]
        knowledge.append(
            {
                "document_id": document_id,
                "title": f"Resolved customer-care case {conversation_id[:8]}",
                "text": resolution,
                "source": f"TweetSumm conversation {conversation_id}",
            }
        )
        cases.append(
            {
                "question": question,
                "expected_document_id": document_id,
                "category": "real_world",
                "difficulty": "natural",
                "provenance": "tweetsumm_real_conversation",
                "source_conversation_id": conversation_id,
                "source_tweet_id": str(first_tweet["tweet_id"]),
            }
        )
    for entry, first_tweet, question, _ in unsupported:
        cases.append(
            {
                "question": question,
                "expected_document_id": None,
                "category": "real_world_unsupported",
                "difficulty": "hard",
                "provenance": "tweetsumm_real_conversation_without_corpus_resolution",
                "source_conversation_id": entry["conversation_id"],
                "source_tweet_id": str(first_tweet["tweet_id"]),
            }
        )
    cases.sort(key=lambda item: hashlib.sha256(f"{name}:{item['question']}".encode()).hexdigest())
    normalized = [re.sub(r"\W+", " ", item["question"].lower()).strip() for item in cases]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"duplicate questions detected in real {name}")
    return knowledge, cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tweetsumm-train", type=Path, required=True)
    parser.add_argument("--twcs", type=Path, required=True)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    paths = {
        "development": OUTPUT / "development.json",
        "validation": OUTPUT / "validation.json",
        "challenge": OUTPUT / "challenge.json",
    }
    if any(path.exists() for path in paths.values()) and not args.rebuild:
        raise SystemExit("real development/validation sets are locked; pass --rebuild for an intentional reset")

    manifest_path = OUTPUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    test_cases = json.loads((OUTPUT / "test.json").read_text(encoding="utf-8"))
    test_conversations = {
        case["source_conversation_id"]
        for case in test_cases
        if case.get("source_conversation_id")
    }
    candidates = [
        item
        for item in load_candidates([args.tweetsumm_train], args.twcs)
        if item[0]["conversation_id"] not in test_conversations
    ]
    candidates.sort(key=lambda item: stable_key(item[0]["conversation_id"]))
    required_candidates = sum(sum(counts) for counts in SPLIT_SIZES.values())
    if len(candidates) < required_candidates:
        raise ValueError(
            f"expected at least {required_candidates} eligible unused conversations, "
            f"found {len(candidates)}"
        )

    all_split_conversations = set()
    offset = 0
    for name, (supported_count, unsupported_count) in SPLIT_SIZES.items():
        split_size = supported_count + unsupported_count
        selected = candidates[offset:offset + split_size]
        offset += split_size
        knowledge, cases = build_split(selected, name, supported_count)
        split_conversations = {case["source_conversation_id"] for case in cases}
        if split_conversations & test_conversations or split_conversations & all_split_conversations:
            raise ValueError("conversation leakage detected across real benchmark splits")
        all_split_conversations.update(split_conversations)

        knowledge_bytes = encoded(knowledge)
        cases_bytes = encoded(cases)
        (OUTPUT / f"{name}_knowledge.json").write_bytes(knowledge_bytes)
        paths[name].write_bytes(cases_bytes)
        manifest[f"{name}_case_count"] = len(cases)
        manifest[f"{name}_supported_count"] = supported_count
        manifest[f"{name}_unsupported_count"] = unsupported_count
        manifest[f"{name}_sha256"] = hashlib.sha256(cases_bytes).hexdigest()
        manifest[f"{name}_knowledge_sha256"] = hashlib.sha256(knowledge_bytes).hexdigest()

    manifest["development_validation_source"] = "TweetSumm final_train_tweetsum.jsonl"
    manifest["development_validation_review_status"] = "source_filtered_unreviewed"
    manifest_path.write_bytes(encoded(manifest))
    print("built non-overlapping real development, validation, and challenge sets")
    print("challenge contains 80 supported and 100 real unsupported messages")


if __name__ == "__main__":
    main()
