#!/usr/bin/env python3
"""Select a deterministic quality-audit sample from automated development labels."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path


SEED = "medusa-development-automation-audit-v1"


def rank(case_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{case_id}".encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet = json.loads(args.packet.read_text(encoding="utf-8"))
    decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    evidence = {item["case_id"]: item for item in packet}
    by_decision: dict[str, list[dict]] = collections.defaultdict(list)
    for decision in decisions:
        if decision["reviewer_decision"] in {"supported", "unsupported"}:
            by_decision[decision["reviewer_decision"]].append(
                {**evidence[decision["case_id"]], **decision}
            )
    sample = []
    for label in ("supported", "unsupported"):
        sample.extend(sorted(by_decision[label], key=lambda item: rank(item["case_id"]))[:15])
    sample.sort(key=lambda item: (item["reviewer_decision"], rank(item["case_id"])))
    if len(sample) != 30:
        raise ValueError("audit requires exactly 15 supported and 15 unsupported cases")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(sample, indent=2, sort_keys=True) + "\n").encode()
    args.output.write_bytes(payload)
    manifest = {
        "seed": SEED,
        "sample_count": len(sample),
        "supported": sum(item["reviewer_decision"] == "supported" for item in sample),
        "unsupported": sum(item["reviewer_decision"] == "unsupported" for item in sample),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "selection_policy": "Stable hash sample selected before audit outcomes are known.",
    }
    (args.output.parent / "quality_audit_sample_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
