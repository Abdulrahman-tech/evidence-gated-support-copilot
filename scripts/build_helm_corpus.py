#!/usr/bin/env python3
"""Build an isolated pinned corpus from official Helm 3 documentation."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess

from support_copilot.helm_ingest import DOCS_PATH, DOCS_VERSION, ingest_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "helm" / "v3"


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
        raise SystemExit("Helm v3 corpus already exists; pass --rebuild to replace")

    actual_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=args.source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual_commit != args.commit:
        raise ValueError("source checkout does not match the requested commit")

    docs_root = args.source / DOCS_PATH
    paths = sorted(
        path
        for path in docs_root.rglob("*")
        if path.is_file() and path.suffix in {".md", ".mdx"}
    )
    if len(paths) < 100:
        raise ValueError(f"expected at least 100 Helm v3 documentation pages, found {len(paths)}")

    raw_documents = [
        document
        for path in paths
        for document in ingest_file(path, args.source, args.commit)
    ]
    unique_by_text = {}
    for document in raw_documents:
        normalized = " ".join(document.text.lower().split())
        unique_by_text.setdefault(normalized, document)
    documents = list(unique_by_text.values())
    if len({document.document_id for document in documents}) != len(documents):
        raise ValueError("duplicate Helm document IDs detected")
    if len(documents) < 250:
        raise ValueError(f"expected at least 250 useful Helm sections, found {len(documents)}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    knowledge_bytes = encoded([asdict(document) for document in documents])
    knowledge_path.write_bytes(knowledge_bytes)
    manifest = {
        "tenant_id": "helm-v3",
        "corpus_id": "helm_v3_official",
        "audience": "developers and platform engineers using Helm 3 with Kubernetes",
        "source_repository": "https://github.com/helm/helm-www",
        "source_commit": args.commit,
        "source_docs_path": DOCS_PATH,
        "source_version": DOCS_VERSION,
        "documentation_license": "CC-BY-4.0",
        "repository_license": "MIT",
        "license_source": "https://helm.sh/",
        "source_page_count": len(paths),
        "document_count": len(documents),
        "duplicate_section_count": len(raw_documents) - len(documents),
        "product_area_counts": dict(
            sorted(Counter(document.product_area for document in documents).items())
        ),
        "knowledge_sha256": hashlib.sha256(knowledge_bytes).hexdigest(),
        "review_status": "machine_ingested_unreviewed",
        "integration_status": "isolated_not_enabled_for_runtime_routing",
        "hosted_model_calls": 0,
    }
    (OUTPUT / "manifest.json").write_bytes(encoded(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
