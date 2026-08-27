#!/usr/bin/env python3
"""Fail closed on provenance, leakage, and schema errors in the large pool."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "medusa" / "benchmark"
FORBIDDEN_FIELDS = {
    "expected_document_id",
    "model_accepts",
    "reviewer_decision",
    "top1_document_id",
    "top2_document_id",
    "top3_document_id",
}


def previous_urls() -> set[str]:
    urls = set()
    for path in BENCHMARK.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            urls.update(item.get("source_url", "") for item in payload)
    discussions = ROOT / "data" / "medusa" / "discussion_sources.json"
    urls.update(
        item["source_url"]
        for item in json.loads(discussions.read_text(encoding="utf-8"))
    )
    return urls


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads(args.sources.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    if len(cases) != manifest["output_count"]:
        raise ValueError("source count does not match manifest")
    if hashlib.sha256(args.sources.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("candidate pool checksum mismatch")
    for field in ("case_id", "source_url", "question"):
        values = [case[field] for case in cases]
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {field}")
    if previous_urls() & {case["source_url"] for case in cases}:
        raise ValueError("candidate pool overlaps a previously reviewed or benchmark source")
    if any(FORBIDDEN_FIELDS & set(case) for case in cases):
        raise ValueError("candidate pool contains labels or retriever predictions")
    if not all(case["label_status"] == "unlabelled_candidate" for case in cases):
        raise ValueError("candidate pool contains a trusted label")
    if not all(case["source_url"].startswith("https://github.com/medusajs/medusa/issues/") for case in cases):
        raise ValueError("unexpected source URL")
    if not all(len(case["body_text_sha256"]) == 64 for case in cases):
        raise ValueError("missing source-body hash")

    print(
        f"validated {len(cases)} authentic unlabelled candidates across "
        f"{len({case['leakage_group_id'] for case in cases})} leakage groups"
    )


if __name__ == "__main__":
    main()
