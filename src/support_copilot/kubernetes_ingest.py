"""Deterministic ingestion helpers for pinned Kubernetes documentation."""

from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path

from support_copilot.models import KnowledgeDocument


FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
TITLE = re.compile(r"^title:\s*['\"]?(.+?)['\"]?\s*$", re.M)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
SHORTCODE = re.compile(r"{{[%<].*?[>%]}}", re.S)
CODE_FENCE = re.compile(r"^```[^\n]*$", re.M)
MARKDOWN_IMAGE = re.compile(r"!\[([^]]*)]\([^)]+\)")
MARKDOWN_LINK = re.compile(r"\[([^]]+)]\([^)]+\)")
REFERENCE_LINK = re.compile(r"\[([^]]+)]\[[^]]*]")
REFERENCE_DEFINITION = re.compile(r"^\[[^]]+]:\s+\S+.*$", re.M)
HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.M)
WHITESPACE = re.compile(r"[ \t]+")


def frontmatter_title(text: str, fallback: str) -> str:
    match = FRONTMATTER.match(text)
    if not match:
        return fallback
    title = TITLE.search(match.group(1))
    return html.unescape(title.group(1)).strip() if title else fallback


def clean_markdown(text: str) -> str:
    text = FRONTMATTER.sub("", text)
    text = HTML_COMMENT.sub("", text)
    text = SHORTCODE.sub("", text)
    text = CODE_FENCE.sub("", text)
    text = MARKDOWN_IMAGE.sub(r"\1", text)
    text = MARKDOWN_LINK.sub(r"\1", text)
    text = REFERENCE_LINK.sub(r"\1", text)
    text = REFERENCE_DEFINITION.sub("", text)
    text = HTML_TAG.sub("", text)
    cleaned = []
    for line in text.splitlines():
        line = WHITESPACE.sub(" ", line).strip()
        if not line or re.fullmatch(r"[:| -]+", line):
            cleaned.append("")
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        cleaned.append(line.replace("`", ""))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()


def split_sections(text: str, page_title: str) -> list[tuple[str, str]]:
    matches = list(HEADING.finditer(text))
    sections = []
    if not matches:
        return [(page_title, text)] if len(text) >= 80 else []
    overview = text[: matches[0].start()].strip()
    if len(overview) >= 80:
        sections.append((page_title, overview))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = re.sub(r"\s+\{#[^}]+}$", "", match.group(2)).strip()
        body = text[start:end].strip()
        if len(body) < 80:
            continue
        title = page_title if heading == page_title else f"{page_title}: {heading}"
        sections.append((title, body))
    return sections


def product_area(relative_path: str) -> str:
    parts = relative_path.split("/")
    docs_index = parts.index("docs")
    return parts[docs_index + 1].replace("-", "_")


def ingest_file(
    path: Path,
    source_root: Path,
    source_commit: str,
) -> list[KnowledgeDocument]:
    relative_path = path.relative_to(source_root).as_posix()
    raw = path.read_text(encoding="utf-8")
    page_title = frontmatter_title(raw, path.stem.replace("-", " ").title())
    cleaned = clean_markdown(raw)
    documents = []
    for section_index, (title, body) in enumerate(split_sections(cleaned, page_title), 1):
        identity = f"{relative_path}#{section_index}:{title}"
        documents.append(
            KnowledgeDocument(
                document_id="kubernetes-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                title=title,
                text=body,
                source=(
                    "https://github.com/kubernetes/website/blob/"
                    f"{source_commit}/{relative_path}"
                ),
                tenant_id="kubernetes",
                product_area=product_area(relative_path),
                source_path=relative_path,
                source_commit=source_commit,
            )
        )
    return documents
