#!/usr/bin/env python3
"""Select a deterministic, diverse manual-review batch from development only."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path


DEFAULT_SEED = "medusa-development-manual-batch-02-v1"
COHORTS = {
    "supported": "high_confidence_match",
    "unsupported": "low_confidence_explicit_issue",
    "deferred": "automation_deferred",
}


def rank(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def select_diverse(
    candidates: list[dict], count: int, used_groups: set[str], seed: str
) -> list[dict]:
    by_area: dict[str, list[dict]] = collections.defaultdict(list)
    for item in candidates:
        by_area[item["proposed_product_area"]].append(item)
    for items in by_area.values():
        items.sort(key=lambda item: rank(seed, item["case_id"]))
    areas = sorted(by_area, key=lambda area: rank(seed, area))
    selected = []
    while len(selected) < count:
        progressed = False
        for area in areas:
            while by_area[area]:
                item = by_area[area].pop(0)
                if item["leakage_group_id"] in used_groups:
                    continue
                selected.append(item)
                used_groups.add(item["leakage_group_id"])
                progressed = True
                break
            if len(selected) == count:
                break
        if not progressed:
            break
    if len(selected) != count:
        raise ValueError(f"could select only {len(selected)} of {count} diverse cases")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--prior-audit", type=Path, required=True)
    parser.add_argument("--v1-decisions", type=Path, required=True)
    parser.add_argument("--exclude-batch", type=Path, action="append", default=[])
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--supported-count", type=int, default=10)
    parser.add_argument("--unsupported-count", type=int, default=10)
    parser.add_argument("--deferred-count", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    packet = json.loads(args.packet.read_text(encoding="utf-8"))
    assignments = json.loads(args.assignments.read_text(encoding="utf-8"))
    prior = json.loads(args.prior_audit.read_text(encoding="utf-8"))
    decisions = json.loads(args.v1_decisions.read_text(encoding="utf-8"))
    excluded_batches = [
        item
        for path in args.exclude_batch
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]
    roles = {item["case_id"]: item["role"] for item in assignments}
    groups = {item["case_id"]: item["leakage_group_id"] for item in assignments}
    prior_ids = {item["case_id"] for item in prior}
    excluded_ids = prior_ids | {item["case_id"] for item in excluded_batches}
    excluded_groups = {
        groups[item["case_id"]]
        for item in prior
        if item["case_id"] in groups
    } | {item["leakage_group_id"] for item in excluded_batches}
    decision_by_id = {item["case_id"]: item["reviewer_decision"] for item in decisions}

    candidates = []
    for item in packet:
        case_id = item["case_id"]
        if (
            roles.get(case_id) != "development"
            or case_id in excluded_ids
            or groups[case_id] in excluded_groups
        ):
            continue
        candidates.append(
            {
                **item,
                "reviewer_decision": "",
                "expected_document_id": "",
                "review_status": "pending",
                "review_notes": "",
                "leakage_group_id": groups[case_id],
                "selection_cohort": COHORTS[decision_by_id[case_id]],
            }
        )

    selected = []
    used_groups: set[str] = set(excluded_groups)
    cohort_targets = {
        "supported": args.supported_count,
        "unsupported": args.unsupported_count,
        "deferred": args.deferred_count,
    }
    if any(count < 0 for count in cohort_targets.values()):
        raise ValueError("cohort counts must be non-negative")
    target_count = sum(cohort_targets.values())
    for decision in ("supported", "unsupported", "deferred"):
        cohort = COHORTS[decision]
        count = cohort_targets[decision]
        if count == 0:
            continue
        selected.extend(
            select_diverse(
                [item for item in candidates if item["selection_cohort"] == cohort],
                count,
                used_groups,
                args.seed,
            )
        )
    selected.sort(
        key=lambda item: (item["selection_cohort"], rank(args.seed, item["case_id"]))
    )

    selected_ids = {item["case_id"] for item in selected}
    if len(selected) != target_count or excluded_ids & selected_ids:
        raise ValueError(f"batch must contain {target_count} unseen cases")
    if any(roles[item["case_id"]] != "development" for item in selected):
        raise ValueError("non-development case entered manual batch")
    if len({item["leakage_group_id"] for item in selected}) != target_count:
        raise ValueError("manual batch contains repeated leakage groups")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(selected, indent=2, sort_keys=True) + "\n").encode()
    args.output.write_bytes(payload)
    manifest = {
        "seed": args.seed,
        "case_count": target_count,
        "cohort_counts": dict(sorted(collections.Counter(
            item["selection_cohort"] for item in selected
        ).items())),
        "product_area_counts": dict(sorted(collections.Counter(
            item["proposed_product_area"] for item in selected
        ).items())),
        "support_intent_counts": dict(sorted(collections.Counter(
            item["support_intent"] for item in selected
        ).items())),
        "prior_audit_overlap": False,
        "prior_manual_batch_overlap": False,
        "excluded_previous_batch_cases": len(excluded_batches),
        "unique_leakage_groups": target_count,
        "role": "development",
        "labels_included": False,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    manifest_path = args.output.with_name(
        args.output.name.removesuffix(".json") + "_manifest.json"
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
