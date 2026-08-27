"""Deterministic ingestion helpers for pinned Helm documentation."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from support_copilot.kubernetes_ingest import (
    clean_markdown as clean_common_markdown,
    frontmatter_title,
    split_sections,
)
from support_copilot.models import KnowledgeDocument


MDX_IMPORT = re.compile(r"^(?:import|export)\s+.*?;\s*$", re.M)
DOCS_VERSION = "3.19.0"
DOCS_PATH = "versioned_docs/version-3"


def clean_markdown(text: str) -> str:
    """Remove Docusaurus-only syntax while retaining Helm examples."""

    return clean_common_markdown(MDX_IMPORT.sub("", text))


def product_area(relative_path: str) -> str:
    parts = relative_path.split("/")
    version_index = parts.index("version-3")
    if version_index + 2 >= len(parts):
        return "overview"
    return parts[version_index + 1].replace("-", "_")


def ingest_file(
    path: Path,
    source_root: Path,
    source_commit: str,
) -> list[KnowledgeDocument]:
    relative_path = path.relative_to(source_root).as_posix()
    raw = path.read_text(encoding="utf-8")
    page_title = frontmatter_title(raw, path.stem.replace("_", " ").title())
    cleaned = clean_markdown(raw)
    documents = []
    for section_index, (title, body) in enumerate(
        split_sections(cleaned, page_title), 1
    ):
        identity = f"{DOCS_VERSION}:{relative_path}#{section_index}:{title}"
        documents.append(
            KnowledgeDocument(
                document_id="helm3-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                title=title,
                text=body,
                source=(
                    "https://github.com/helm/helm-www/blob/"
                    f"{source_commit}/{relative_path}"
                ),
                tenant_id="helm-v3",
                product_area=product_area(relative_path),
                source_path=relative_path,
                source_commit=source_commit,
            )
        )
    return documents
