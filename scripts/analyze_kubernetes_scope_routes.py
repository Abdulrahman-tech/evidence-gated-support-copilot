#!/usr/bin/env python3
"""Measure explicit adjacent-corpus demand in the excluded Kubernetes pilot."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from support_copilot.scope import (
    KUBERNETES_SCOPE_ROUTER_VERSION,
    KubernetesScopeRouter,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "kubernetes" / "source_yield_pilot" / "review_packet.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "kubernetes_scope_route_demand_20260826.json"


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(rows: list[dict], input_sha256: str) -> dict:
    case_ids = [row["case_id"] for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("pilot case IDs must be unique")

    router = KubernetesScopeRouter()
    cases = []
    route_counts: Counter[str] = Counter()
    for row in rows:
        route = router.route(row["question"])
        route_counts[route.name] += 1
        cases.append(
            {
                "case_id": row["case_id"],
                "question": row["question"],
                "source_tags": row["source_tags"],
                "scope_route": route.name,
                "passed_to_core_retrieval": route.in_scope,
            }
        )

    routed_out_count = sum(
        count for route, count in route_counts.items() if route != "kubernetes_core"
    )
    return {
        "analysis_id": "kubernetes_scope_route_demand_20260826",
        "analysis_role": "diagnostic_on_source_yield_pilot_excluded_from_evaluation",
        "interpretation": (
            "Title-only explicit-route demand, not a population prevalence or corpus-coverage estimate. "
            "kubernetes_core means the case proceeds to retrieval and evidence verification; it does not mean supported."
        ),
        "router_version": KUBERNETES_SCOPE_ROUTER_VERSION,
        "input_sha256": input_sha256,
        "case_count": len(rows),
        "hosted_model_calls": 0,
        "passed_to_core_retrieval_count": route_counts["kubernetes_core"],
        "explicitly_routed_out_count": routed_out_count,
        "explicitly_routed_out_rate": routed_out_count / len(rows) if rows else 0.0,
        "route_counts": dict(sorted(route_counts.items())),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("pilot input must be a non-empty JSON list")

    manifest_path = args.input.with_name("manifest.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("packet_sha256") != sha256(args.input):
            raise ValueError("pilot packet checksum mismatch")
        if manifest.get("case_count") != len(rows):
            raise ValueError("pilot case count does not match its manifest")

    report = analyze(rows, sha256(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded(report))
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
