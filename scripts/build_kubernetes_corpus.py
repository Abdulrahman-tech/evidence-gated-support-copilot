#!/usr/bin/env python3
"""Build a pinned corpus from official English Kubernetes documentation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from support_copilot.kubernetes_ingest import ingest_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "kubernetes"
SOURCE_AREAS = ("concepts", "setup", "tasks", "tutorials", "reference")


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    knowledge_path = OUTPUT / "knowledge.json"
    if knowledge_path.exists() and not args.rebuild:
        raise SystemExit("Kubernetes corpus already exists; pass --rebuild to replace")
    actual_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=args.source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual_commit != args.commit:
        raise ValueError("source checkout does not match the requested commit")

    docs_root = args.source / "content" / "en" / "docs"
    paths = sorted(
        path
        for area in SOURCE_AREAS
        for path in (docs_root / area).rglob("*.md")
        if path.name != "_index.md"
    )
    raw_documents = [
        document for path in paths for document in ingest_file(path, args.source, args.commit)
    ]
    unique_by_text = {}
    for document in raw_documents:
        normalized = " ".join(document.text.lower().split())
        unique_by_text.setdefault(normalized, document)
    documents = list(unique_by_text.values())
    if len({document.document_id for document in documents}) != len(documents):
        raise ValueError("duplicate Kubernetes document IDs detected")
    if len(documents) < 2_000:
        raise ValueError(f"expected at least 2,000 useful sections, found {len(documents)}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    knowledge_bytes = encoded([asdict(document) for document in documents])
    knowledge_path.write_bytes(knowledge_bytes)
    manifest = {
        "tenant_id": "kubernetes",
        "audience": "platform engineers, SREs, and developers operating Kubernetes",
        "source_repository": "https://github.com/kubernetes/website",
        "source_commit": args.commit,
        "license": "CC-BY-4.0",
        "source_areas": list(SOURCE_AREAS),
        "source_page_count": len(paths),
        "document_count": len(documents),
        "duplicate_section_count": len(raw_documents) - len(documents),
        "product_area_counts": dict(
            sorted(Counter(document.product_area for document in documents).items())
        ),
        "knowledge_sha256": hashlib.sha256(knowledge_bytes).hexdigest(),
        "review_status": "machine_ingested_unreviewed",
    }
    (OUTPUT / "manifest.json").write_bytes(encoded(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
