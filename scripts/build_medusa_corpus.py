#!/usr/bin/env python3
"""Build a pinned, provenance-rich corpus from official Medusa documentation."""

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from support_copilot.medusa_ingest import ingest_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "medusa"
PRODUCT_AREAS = (
    "auth",
    "customer",
    "fulfillment",
    "inventory",
    "order",
    "payment",
    "product",
)


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
        raise SystemExit("Medusa corpus already exists; pass --rebuild to replace it")

    docs_root = args.source / "www" / "apps" / "resources" / "app" / "commerce-modules"
    paths = sorted(
        path
        for product_area in PRODUCT_AREAS
        for path in (docs_root / product_area).rglob("page.mdx")
        if "admin-widget-zones" not in path.parts
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
    duplicate_section_count = len(raw_documents) - len(documents)
    document_ids = [document.document_id for document in documents]
    if len(set(document_ids)) != len(document_ids):
        raise ValueError("duplicate Medusa document IDs detected")
    if len(documents) < 100:
        raise ValueError(f"expected at least 100 useful documentation sections, found {len(documents)}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    knowledge_bytes = encoded([asdict(document) for document in documents])
    knowledge_path.write_bytes(knowledge_bytes)
    manifest = {
        "tenant_id": "medusa",
        "audience": "merchants and developers operating Medusa stores",
        "source_repository": "https://github.com/medusajs/medusa",
        "source_commit": args.commit,
        "license": "MIT; Enterprise Edition paths are excluded",
        "product_areas": list(PRODUCT_AREAS),
        "source_page_count": len(paths),
        "document_count": len(documents),
        "duplicate_section_count": duplicate_section_count,
        "knowledge_sha256": hashlib.sha256(knowledge_bytes).hexdigest(),
        "review_status": "machine_ingested_unreviewed",
    }
    (OUTPUT / "manifest.json").write_bytes(encoded(manifest))
    print(
        f"built {len(documents)} Medusa knowledge sections from "
        f"{len(paths)} official documentation pages"
    )


if __name__ == "__main__":
    main()
