#!/usr/bin/env python3
"""Build the broader pinned Medusa corpus used for authentic Q&A mapping."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from support_copilot.medusa_ingest import ingest_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "medusa"
SOURCE_AREAS = (
    "admin-components",
    "commerce-modules",
    "create-medusa-app",
    "deployment",
    "how-to-tutorials",
    "infrastructure-modules",
    "integrations",
    "js-sdk",
    "medusa-cli",
    "nextjs-starter",
    "plugins",
    "recipes",
    "storefront-development",
    "troubleshooting",
)


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    knowledge_path = OUTPUT / "knowledge_expanded.json"
    manifest_path = OUTPUT / "expanded_manifest.json"
    if knowledge_path.exists() and not args.rebuild:
        raise SystemExit("expanded corpus already exists; pass --rebuild to replace")

    docs_root = args.source / "www" / "apps" / "resources" / "app"
    paths = sorted(
        path
        for area in SOURCE_AREAS
        for path in (docs_root / area).rglob("page.mdx")
        if "enterprise" not in {part.lower() for part in path.parts}
        and "admin-widget-injection-zones" not in path.parts
    )
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
    document_ids = [document.document_id for document in documents]
    if len(set(document_ids)) != len(document_ids):
        raise ValueError("duplicate Medusa document IDs detected")
    if len(documents) < 1_000:
        raise ValueError(f"expected at least 1,000 useful sections, found {len(documents)}")

    knowledge_bytes = encoded([asdict(document) for document in documents])
    knowledge_path.write_bytes(knowledge_bytes)
    area_counts = Counter(document.product_area for document in documents)
    manifest_path.write_bytes(
        encoded(
            {
                "tenant_id": "medusa",
                "audience": "merchants and developers operating Medusa stores",
                "source_repository": "https://github.com/medusajs/medusa",
                "source_commit": args.commit,
                "license": "MIT; paths marked Enterprise Edition are excluded",
                "source_areas": list(SOURCE_AREAS),
                "source_page_count": len(paths),
                "document_count": len(documents),
                "duplicate_section_count": len(raw_documents) - len(documents),
                "product_area_counts": dict(sorted(area_counts.items())),
                "knowledge_sha256": hashlib.sha256(knowledge_bytes).hexdigest(),
                "review_status": "machine_ingested_unreviewed",
            }
        )
    )
    print(
        f"built {len(documents)} expanded Medusa sections from "
        f"{len(paths)} official documentation pages"
    )


if __name__ == "__main__":
    main()
