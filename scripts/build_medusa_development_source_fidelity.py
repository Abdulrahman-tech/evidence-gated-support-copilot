#!/usr/bin/env python3
"""Build a development-only audit packet from full public source questions."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path

from support_copilot.knowledge import KnowledgeBase
from support_copilot.medusa_discussions import normalize_text, visible_text
from support_copilot.models import KnowledgeDocument


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
USER_AGENT = "evidence-gated-support-copilot/0.1 (public benchmark audit)"
IMPORTANT_ISSUE_SECTIONS = (
    "issue summary",
    "what happened",
    "what happended",
    "how can this issue be resolved",
    "expected behavior",
    "actual behavior",
    "what medusa version and documentation are you using",
)
BOILERPLATE_SECTIONS = (
    "package.json",
    "node.js version",
    "database and its version",
    "operating system name and version",
    "browser name",
    "preliminary checks",
    "link to reproduction repo",
    "my package.json",
)
HEADING = re.compile(r"(?m)^#{2,4}\s+(.+?)\s*$")
IMAGE = re.compile(r"!\[[^]]*]\([^)]*\)")
HTML_TAG = re.compile(r"<[^>]+>")
HTML_HEADING = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.I | re.S)
HTML_BLOCK_END = re.compile(r"</(?:p|div|li|pre|blockquote)>", re.I)
TITLE_PREFIX = re.compile(r"^\s*\[(?:bug|feature|improvement)]\s*:\s*", re.I)
MAX_QUESTION_CHARACTERS = 1_600
MEDUSA_VERSION = re.compile(
    r'"(?:@medusajs/medusa|medusa)"\s*:\s*"([^"\s]+)"',
    re.I,
)


class JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.payloads: list[str] = []
        self._capturing = False
        self._text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._capturing = True
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capturing:
            self.payloads.append("".join(self._text))
            self._capturing = False
            self._text = []


def source_question_from_page(page: str) -> tuple[str, str, str]:
    """Return source title, structured body, and canonical body from GitHub JSON-LD."""

    parser = JsonLdParser()
    parser.feed(page)
    for raw_payload in parser.payloads:
        payload = json.loads(raw_payload)
        if payload.get("@type") == "QAPage":
            question = payload.get("mainEntity", {})
            title = normalize_text(question.get("name", ""))
            raw_body = question.get("text", "")
            canonical_body = visible_text(raw_body)
            raw_body = HTML_HEADING.sub(
                lambda match: f"\n### {visible_text(match.group(1))}\n",
                raw_body,
            )
            raw_body = HTML_BLOCK_END.sub("\n", raw_body)
            body = html.unescape(HTML_TAG.sub(" ", raw_body)).strip()
        elif payload.get("@type") == "DiscussionForumPosting":
            title = normalize_text(payload.get("headline", ""))
            body = html.unescape(payload.get("articleBody", "")).strip()
            canonical_body = normalize_text(body)
        else:
            continue
        if title and body:
            return title, body, canonical_body
    raise ValueError("GitHub page has no usable question JSON-LD")


def clean_context(value: str) -> str:
    value = IMAGE.sub("", value)
    value = HTML_TAG.sub(" ", value)
    value = html.unescape(value)
    return normalize_text(value.replace("```", " "))


def issue_context(body: str) -> str:
    pieces = HEADING.split(body)
    selected = []
    for index in range(1, len(pieces), 2):
        heading = normalize_text(pieces[index]).lower().rstrip("?")
        section = pieces[index + 1] if index + 1 < len(pieces) else ""
        if any(heading.startswith(prefix) for prefix in IMPORTANT_ISSUE_SECTIONS):
            cleaned = clean_context(section)
            if cleaned and cleaned.lower() not in {"no response", "n/a"}:
                selected.append(f"{pieces[index]}: {cleaned}")
    if selected:
        return normalize_text(" ".join(selected))
    return clean_context(body)


def discussion_context(body: str) -> str:
    pieces = HEADING.split(body)
    if len(pieces) == 1:
        return clean_context(body)
    selected = [clean_context(pieces[0])]
    for index in range(1, len(pieces), 2):
        heading = normalize_text(pieces[index]).lower().rstrip("?")
        section = pieces[index + 1] if index + 1 < len(pieces) else ""
        if any(heading.startswith(prefix) for prefix in BOILERPLATE_SECTIONS):
            continue
        cleaned = clean_context(section)
        if cleaned:
            selected.append(f"{pieces[index]}: {cleaned}")
    return normalize_text(" ".join(selected))


def source_faithful_question(title: str, body: str, source_type: str) -> str:
    clean_title = normalize_text(TITLE_PREFIX.sub("", title))
    context = issue_context(body) if "issue" in source_type else discussion_context(body)
    versions = sorted(set(MEDUSA_VERSION.findall(body)))
    version_context = (
        f" Reported Medusa version: {', '.join(versions)}." if versions else ""
    )
    prefix = f"{clean_title}.{version_context} Source context: "
    available = MAX_QUESTION_CHARACTERS - len(prefix)
    if len(context) > available:
        context = context[: max(0, available - 1)].rstrip() + "…"
    return prefix + context


def fetch(url: str, cache_path: Path, refresh: bool) -> str:
    if cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        page = response.read().decode("utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(page, encoding="utf-8")
    return page


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/private/tmp/medusa-development-source-fidelity"),
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--decisions",
        type=Path,
        help="Explicit complete decision policy used to approve the audit packet.",
    )
    args = parser.parse_args()
    if args.workers <= 0:
        raise ValueError("workers must be positive")

    development = json.loads((DATA / "benchmark" / "development.json").read_text())
    issue_sources = {
        row["case_id"]: row
        for row in json.loads((DATA / "candidate_pool" / "sources.json").read_text())
    }
    discussion_sources = {
        row["case_id"]: row
        for row in json.loads((DATA / "discussion_sources.json").read_text())
    }
    source_metadata = {**issue_sources, **discussion_sources}
    documents = [
        KnowledgeDocument(**row)
        for row in json.loads((DATA / "knowledge_expanded.json").read_text())
    ]
    knowledge_base = KnowledgeBase(documents)

    collected: dict[str, tuple[str, str, str]] = {}
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for case in development:
            source_url = case["source_url"]
            cache_path = args.cache_dir / f"{case['case_id']}.html"
            future = executor.submit(fetch, source_url, cache_path, args.refresh)
            futures[future] = case
        for future in as_completed(futures):
            case = futures[future]
            try:
                collected[case["case_id"]] = source_question_from_page(future.result())
            except Exception as error:
                failures[case["case_id"]] = f"{type(error).__name__}: {error}"
    if failures:
        raise RuntimeError(f"source collection failed: {failures}")

    packet = []
    for case in development:
        case_id = case["case_id"]
        source_title, source_body, canonical_source_body = collected[case_id]
        metadata = source_metadata[case_id]
        normalized_hash = hashlib.sha256(canonical_source_body.encode()).hexdigest()
        expected_hash = metadata.get(
            "body_text_sha256",
            metadata.get("question_text_sha256"),
        )
        reviewed_question = source_faithful_question(
            source_title,
            source_body,
            case["source_type"],
        )
        candidates = knowledge_base.search(reviewed_question, limit=3, tenant_id="medusa")
        packet.append(
            {
                "case_id": case_id,
                "source_url": case["source_url"],
                "source_type": case["source_type"],
                "source_labels": metadata.get("source_labels", []),
                "source_title": source_title,
                "source_word_count": len(canonical_source_body.split()),
                "source_question_sha256": normalized_hash,
                "source_hash_matches": normalized_hash == expected_hash,
                "original_question": case["question"],
                "reviewed_question": reviewed_question,
                "current_expected_document_id": case["expected_document_id"],
                "top_candidates": [
                    {
                        "document_id": candidate.document_id,
                        "title": candidate.title,
                        "passage": candidate.passage,
                        "score": candidate.score,
                    }
                    for candidate in candidates
                ],
                "reviewer_decision": "",
                "expected_document_id": "",
                "review_status": "pending",
                "review_notes": "",
            }
        )

    packet.sort(key=lambda row: row["case_id"])
    if args.decisions:
        policy = json.loads(args.decisions.read_text(encoding="utf-8"))
        supported = policy.get("supported", {})
        unsupported = set(policy.get("unsupported", []))
        outdated = set(policy.get("outdated", []))
        decision_ids = set(supported) | unsupported | outdated
        packet_ids = {row["case_id"] for row in packet}
        if decision_ids != packet_ids:
            raise ValueError("decision policy must explicitly cover every packet case once")
        if (set(supported) & unsupported) or (set(supported) & outdated) or (
            unsupported & outdated
        ):
            raise ValueError("decision policy case groups overlap")
        document_ids = {document.document_id for document in documents}
        if not set(supported.values()) <= document_ids:
            raise ValueError("decision policy references an unknown evidence document")
        notes = policy.get("notes", {})
        for row in packet:
            case_id = row["case_id"]
            if case_id in supported:
                row["reviewer_decision"] = "supported"
                row["expected_document_id"] = supported[case_id]
            elif case_id in outdated:
                row["reviewer_decision"] = "outdated"
            else:
                row["reviewer_decision"] = "unsupported"
            row["review_status"] = "approved"
            row["review_notes"] = notes.get(
                case_id,
                "Full source context and pinned candidate evidence reviewed.",
            )
            row["review_method"] = policy["review_method"]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(packet, indent=2, sort_keys=True) + "\n").encode()
    args.output.write_bytes(payload)
    summary = {
        "case_count": len(packet),
        "issue_count": sum("issue" in row["source_type"] for row in packet),
        "discussion_count": sum("discussion" in row["source_type"] for row in packet),
        "source_hash_match_count": sum(row["source_hash_matches"] for row in packet),
        "changed_question_count": sum(
            row["reviewed_question"] != row["original_question"] for row in packet
        ),
        "packet_sha256": hashlib.sha256(payload).hexdigest(),
        "scope": "development_only",
        "review_status": "approved" if args.decisions else "pending",
        "review_method": policy["review_method"] if args.decisions else None,
    }
    (args.output.parent / "manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
