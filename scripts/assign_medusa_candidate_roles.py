#!/usr/bin/env python3
"""Freeze candidate roles before adjudication without splitting topic groups."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path


SEED = "medusa-candidate-role-assignment-v1"
ROLE_THRESHOLDS = (
    ("development", 0.34),
    ("validation", 0.61),
    ("locked_test", 0.88),
    ("reserve", 1.0),
)


def role_for_group(group_id: str) -> str:
    digest = hashlib.sha256(f"{SEED}:{group_id}".encode()).hexdigest()
    value = int(digest[:16], 16) / float(16**16)
    return next(role for role, threshold in ROLE_THRESHOLDS if value < threshold)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    source_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    source_sha256 = hashlib.sha256(args.sources.read_bytes()).hexdigest()
    if source_sha256 != source_manifest["sha256"]:
        raise ValueError("candidate source checksum mismatch")

    group_roles = {
        item["leakage_group_id"]: role_for_group(item["leakage_group_id"])
        for item in sources
    }
    assignments = [
        {
            "case_id": item["case_id"],
            "leakage_group_id": item["leakage_group_id"],
            "role": group_roles[item["leakage_group_id"]],
        }
        for item in sources
    ]
    assignments.sort(key=lambda item: item["case_id"])
    role_counts = collections.Counter(item["role"] for item in assignments)
    if min(role_counts["validation"], role_counts["locked_test"]) < 350:
        raise ValueError("assignment produced insufficient blind-review candidates")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(assignments, indent=2, sort_keys=True) + "\n").encode()
    args.output.write_bytes(payload)
    manifest = {
        "seed": SEED,
        "source_sha256": source_sha256,
        "assignment_sha256": hashlib.sha256(payload).hexdigest(),
        "case_count": len(assignments),
        "group_count": len(group_roles),
        "role_counts": dict(sorted(role_counts.items())),
        "policy": (
            "Roles were assigned before adjudication by a stable hash of the topic "
            "leakage group; every group belongs to exactly one role."
        ),
    }
    (args.output.parent / "assignment_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
