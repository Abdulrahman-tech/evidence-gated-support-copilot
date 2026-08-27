"""Deterministic ingestion helpers for official Medusa MDX documentation."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.S)
CODE_FENCE = re.compile(r"```.*?```", re.S)
IMPORT_LINE = re.compile(r"^import\s+.*$", re.M)
EXPORT_BLOCK = re.compile(r"^export\s+(?:const|default).*?(?=\n\S|\Z)", re.M | re.S)
JSX_TAG = re.compile(r"</?[A-Z][^>]*>")
MARKDOWN_LINK = re.compile(r"\[([^]]+)]\([^)]+\)")
MARKDOWN_IMAGE = re.compile(r"!\[([^]]*)]\([^)]+\)")
METADATA_TITLE = re.compile(r"\btitle:\s*[`\"']([^`\"']+)[`\"']")
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.M)
WHITESPACE = re.compile(r"[ \t]+")
AREA_ALIASES = {
    "admin-components": "admin",
    "create-medusa-app": "installation",
    "how-to-tutorials": "tutorials",
    "infrastructure-modules": "infrastructure",
    "js-sdk": "sdk",
    "medusa-cli": "cli",
    "nextjs-starter": "storefront",
    "storefront-development": "storefront",
}


@dataclass(frozen=True)
class IngestedSection:
    document_id: str
    title: str
    text: str
    source: str
    tenant_id: str
    product_area: str
    source_path: str
    source_commit: str


def clean_mdx(text: str) -> str:
    title_match = METADATA_TITLE.search(text)
    if title_match:
        text = text.replace("{metadata.title}", title_match.group(1))
    text = FRONTMATTER.sub("", text)
    text = CODE_FENCE.sub("", text)
    text = IMPORT_LINE.sub("", text)
    text = EXPORT_BLOCK.sub("", text)
    text = JSX_TAG.sub("", text)
    text = MARKDOWN_IMAGE.sub(r"\1", text)
    text = MARKDOWN_LINK.sub(r"\1", text)
    text = text.replace("{metadata.title}", "")
    cleaned = []
    for line in text.splitlines():
        line = WHITESPACE.sub(" ", line).strip()
        if not line or line in {"---", "</>", "<>", "}"}:
            cleaned.append("")
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        line = line.replace("`", "")
        cleaned.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()


def split_sections(text: str) -> list[tuple[str, str]]:
    matches = list(HEADING.finditer(text))
    if not matches:
        return []
    page_title = matches[0].group(2).strip()
    sections = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(2).strip()
        body = text[start:end].strip()
        if len(body) < 80:
            continue
        title = page_title if heading == page_title else f"{page_title}: {heading}"
        sections.append((title, body))
    return sections


def ingest_file(
    path: Path,
    source_root: Path,
    source_commit: str,
) -> list[IngestedSection]:
    relative_path = path.relative_to(source_root).as_posix()
    parts = relative_path.split("/")
    try:
        product_area = parts[parts.index("commerce-modules") + 1]
        if product_area.endswith(".mdx"):
            product_area = "commerce"
    except (ValueError, IndexError):
        try:
            docs_area = parts[parts.index("app") + 1]
        except (ValueError, IndexError) as error:
            raise ValueError(f"not a Medusa resource documentation path: {path}") from error
        product_area = AREA_ALIASES.get(docs_area, docs_area.replace("-", "_"))
    cleaned = clean_mdx(path.read_text(encoding="utf-8"))
    documents = []
    for section_index, (title, body) in enumerate(split_sections(cleaned), 1):
        identity = f"{relative_path}#{section_index}:{title}"
        document_id = "medusa-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
        documents.append(
            IngestedSection(
                document_id=document_id,
                title=title,
                text=body,
                source=(
                    "https://github.com/medusajs/medusa/blob/"
                    f"{source_commit}/{relative_path}"
                ),
                tenant_id="medusa",
                product_area=product_area,
                source_path=relative_path,
                source_commit=source_commit,
            )
        )
    return documents
