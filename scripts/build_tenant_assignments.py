#!/usr/bin/env python3
"""Recover company routing metadata without changing benchmark questions or labels."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "real_benchmark"
OUTPUT = BENCHMARK / "tenant_assignments.json"


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tweetsumm", type=Path, nargs="+", required=True)
    parser.add_argument("--twcs", type=Path, required=True)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if OUTPUT.exists() and not args.rebuild:
        raise SystemExit("tenant assignments already exist; pass --rebuild to replace")

    target_conversations = set()
    for split in ("development", "validation", "challenge", "test"):
        cases = json.loads((BENCHMARK / f"{split}.json").read_text(encoding="utf-8"))
        target_conversations.update(
            case["source_conversation_id"]
            for case in cases
            if case.get("source_conversation_id")
        )

    tweet_to_conversation = {}
    for path in args.tweetsumm:
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            conversation_id = entry["conversation_id"]
            if conversation_id not in target_conversations:
                continue
            for turn in entry["tweet_ids_sentence_offset"]:
                tweet_to_conversation[str(turn["tweet_id"])] = conversation_id

    tenants_by_conversation = defaultdict(set)
    with args.twcs.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            conversation_id = tweet_to_conversation.get(row["tweet_id"])
            if conversation_id and row["inbound"].lower() == "false":
                tenants_by_conversation[conversation_id].add(row["author_id"])

    missing = target_conversations - tenants_by_conversation.keys()
    ambiguous = {
        conversation_id: sorted(tenants)
        for conversation_id, tenants in tenants_by_conversation.items()
        if len(tenants) != 1
    }
    if missing or ambiguous:
        raise ValueError(
            f"tenant routing must be unambiguous; missing={len(missing)}, "
            f"ambiguous={len(ambiguous)}"
        )
    assignments = {
        conversation_id: next(iter(tenants_by_conversation[conversation_id]))
        for conversation_id in sorted(target_conversations)
    }
    assignment_bytes = encoded(assignments)
    OUTPUT.write_bytes(assignment_bytes)

    manifest_path = BENCHMARK / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tenant_assignment_count"] = len(assignments)
    manifest["tenant_assignment_sha256"] = hashlib.sha256(
        assignment_bytes
    ).hexdigest()
    manifest["tenant_assignment_source"] = (
        "outbound support author_id recovered from the recorded TweetSumm/TWCS conversation"
    )
    manifest_path.write_bytes(encoded(manifest))
    print(f"wrote {len(assignments)} unambiguous tenant assignments")


if __name__ == "__main__":
    main()
