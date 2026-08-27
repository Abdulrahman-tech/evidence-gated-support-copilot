"""Parse public Medusa GitHub Discussions without storing redistributed bodies."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit


DISCUSSION_LINK = re.compile(r"^/medusajs/medusa/discussions/(\d+)$")
WHITESPACE = re.compile(r"\s+")
WORD = re.compile(r"[a-z0-9]+")
RAW_URL = re.compile(r"https?://[^\s<>\"']+")
OFFICIAL_DOCUMENT_HOST = "docs.medusajs.com"


class _DiscussionLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: dict[int, str] = {}
        self._number: int | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        match = DISCUSSION_LINK.fullmatch(href)
        if match:
            self._number = int(match.group(1))
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._number is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._number is not None:
            title = normalize_text(" ".join(self._text))
            if title:
                self.links[self._number] = title
            self._number = None
            self._text = []


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.payloads: list[str] = []
        self._capture = False
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._capture = True
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capture:
            self.payloads.append("".join(self._text))
            self._capture = False
            self._text = []


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


@dataclass(frozen=True)
class DiscussionQuestion:
    number: int
    title: str
    source_url: str
    accepted_answer_url: str
    question_word_count: int
    answer_word_count: int
    question_text_sha256: str
    accepted_answer_text_sha256: str
    accepted_answer_official_document_urls: tuple[str, ...] = ()


def normalize_text(value: str) -> str:
    return WHITESPACE.sub(" ", html.unescape(value)).strip()


def visible_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    return normalize_text(" ".join(parser.text))


def extract_official_document_links(value: str) -> tuple[str, ...]:
    parser = _LinkParser()
    parser.feed(value)
    candidates = parser.links + RAW_URL.findall(html.unescape(value))
    links = set()
    for candidate in candidates:
        cleaned = candidate.rstrip(".,);]}")
        parsed = urlsplit(cleaned)
        if parsed.scheme not in {"http", "https"}:
            continue
        if (parsed.hostname or "").lower() != OFFICIAL_DOCUMENT_HOST:
            continue
        path = parsed.path.rstrip("/") or "/"
        links.add(urlunsplit(("https", OFFICIAL_DOCUMENT_HOST, path, "", "")))
    return tuple(sorted(links))


def extract_discussion_links(page: str) -> dict[int, str]:
    parser = _DiscussionLinkParser()
    parser.feed(page)
    return parser.links


def extract_answered_discussion(page: str, number: int) -> DiscussionQuestion | None:
    parser = _JsonLdParser()
    parser.feed(page)
    for raw_payload in parser.payloads:
        payload = json.loads(raw_payload)
        if payload.get("@type") != "QAPage":
            continue
        question = payload.get("mainEntity", {})
        accepted = question.get("acceptedAnswer")
        if not accepted:
            return None
        question_text = visible_text(question.get("text", ""))
        answer_text = visible_text(accepted.get("text", ""))
        title = normalize_text(question.get("name", ""))
        if not title or not question_text or not answer_text:
            return None
        return DiscussionQuestion(
            number=number,
            title=title,
            source_url=f"https://github.com/medusajs/medusa/discussions/{number}",
            accepted_answer_url=accepted.get("url", ""),
            question_word_count=len(question_text.split()),
            answer_word_count=len(answer_text.split()),
            question_text_sha256=hashlib.sha256(question_text.encode()).hexdigest(),
            accepted_answer_text_sha256=hashlib.sha256(answer_text.encode()).hexdigest(),
            accepted_answer_official_document_urls=extract_official_document_links(
                accepted.get("text", "")
            ),
        )
    return None


def title_tokens(title: str) -> set[str]:
    return {
        token[:-1] if len(token) > 3 and token.endswith("s") else token
        for token in WORD.findall(title.lower())
    }


def near_duplicate(left: str, right: str, threshold: float = 0.9) -> bool:
    left_tokens = title_tokens(left)
    right_tokens = title_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens) >= threshold


def deduplicate_discussions(
    questions: list[DiscussionQuestion],
) -> tuple[list[DiscussionQuestion], dict[int, int]]:
    unique: list[DiscussionQuestion] = []
    duplicates: dict[int, int] = {}
    for question in sorted(questions, key=lambda item: item.number, reverse=True):
        duplicate = next(
            (existing for existing in unique if near_duplicate(question.title, existing.title)),
            None,
        )
        if duplicate:
            duplicates[question.number] = duplicate.number
        else:
            unique.append(question)
    return unique, duplicates
