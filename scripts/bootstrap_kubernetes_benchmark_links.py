#!/usr/bin/env python3
"""Build an audit queue from accepted answers linking official Kubernetes docs."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = ROOT / "data" / "kubernetes" / "question_pool" / "accepted_questions.json"
DEFAULT_KNOWLEDGE = ROOT / "data" / "kubernetes" / "knowledge.json"
DEFAULT_PILOT = ROOT / "data" / "kubernetes" / "source_yield_pilot" / "review_packet.json"
DEFAULT_OUTPUT = ROOT / "data" / "kubernetes" / "benchmark_bootstrap"
API_ROOT = "https://api.stackexchange.com/2.3/answers/"
USER_AGENT = "ai-support-copilot-benchmark/0.1 (attributed public research collector)"


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attributes).get("href")
        if href:
            self.links.append(html.unescape(href))


def normalize_official_document_url(raw: str) -> str | None:
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if (parsed.hostname or "").lower() not in {"kubernetes.io", "www.kubernetes.io"}:
        return None
    path = parsed.path.rstrip("/") + "/"
    if not path.startswith("/docs/"):
        return None
    return urllib.parse.urlunsplit(("https", "kubernetes.io", path, "", ""))


def official_document_urls(body: str) -> list[str]:
    parser = LinkParser()
    parser.feed(body)
    return sorted(
        {
            normalized
            for link in parser.links
            if (normalized := normalize_official_document_url(link)) is not None
        }
    )


def official_document_references(body: str) -> list[dict[str, str]]:
    parser = LinkParser()
    parser.feed(body)
    references = set()
    for link in parser.links:
        page_url = normalize_official_document_url(link)
        if page_url is None:
            continue
        anchor = urllib.parse.unquote(urllib.parse.urlsplit(link).fragment).lower()
        references.add((page_url, anchor))
    return [
        {"page_url": page_url, "anchor": anchor}
        for page_url, anchor in sorted(references)
    ]


def heading_anchor(title: str) -> str:
    heading = title.split(": ", 1)[-1].lower()
    heading = re.sub(r"[^a-z0-9 -]", "", heading)
    return re.sub(r"[- ]+", "-", heading).strip("-")


def corpus_url_index(documents: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for document in documents:
        source_path = document.get("source_path", "")
        prefix = "content/en"
        if not source_path.startswith(prefix) or not source_path.endswith(".md"):
            continue
        page = source_path[len(prefix) : -3]
        for suffix in ("/_index", "/index"):
            if page.endswith(suffix):
                page = page[: -len(suffix)]
                break
        url = "https://kubernetes.io" + page.rstrip("/") + "/"
        values = index.setdefault(
            url,
            {
                "document_ids": set(),
                "source_paths": set(),
                "anchor_document_ids": {},
            },
        )
        values["document_ids"].add(document["document_id"])
        values["source_paths"].add(source_path)
        anchor = heading_anchor(document.get("title", ""))
        if anchor:
            values["anchor_document_ids"].setdefault(anchor, set()).add(
                document["document_id"]
            )
    return index


def fetch_answers(answer_ids: list[int], cache_dir: Path, delay: float) -> tuple[list[dict], int | None]:
    answers: list[dict] = []
    quota_remaining = None
    for offset in range(0, len(answer_ids), 100):
        batch = answer_ids[offset : offset + 100]
        batch_digest = hashlib.sha256(
            ",".join(map(str, batch)).encode("utf-8")
        ).hexdigest()[:16]
        cache_path = cache_dir / f"answers-{batch_digest}.json"
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            if delay:
                time.sleep(delay)
            url = API_ROOT + ";".join(map(str, batch)) + "?" + urllib.parse.urlencode(
                {"site": "stackoverflow", "filter": "withbody", "pagesize": 100}
            )
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(encoded(payload))
        if payload.get("backoff"):
            time.sleep(float(payload["backoff"]))
        quota_remaining = payload.get("quota_remaining", quota_remaining)
        answers.extend(payload.get("items", []))
    return answers, quota_remaining


def build_candidates(
    questions: list[dict],
    answers: list[dict],
    pilot_case_ids: set[str],
    url_index: dict[str, dict[str, set[str]]],
) -> list[dict]:
    questions_by_answer = {
        question["accepted_answer_id"]: question
        for question in questions
        if question.get("accepted_answer_id")
        and question["case_id"] not in pilot_case_ids
    }
    candidates = []
    for answer in answers:
        question = questions_by_answer.get(answer.get("answer_id"))
        if question is None:
            continue
        references = official_document_references(answer.get("body", ""))
        links = sorted({reference["page_url"] for reference in references})
        if not links:
            continue
        mapped_ids: set[str] = set()
        mapped_paths: set[str] = set()
        anchor_ids: set[str] = set()
        for link in links:
            mapped = url_index.get(link)
            if mapped:
                mapped_ids.update(mapped["document_ids"])
                mapped_paths.update(mapped["source_paths"])
        for reference in references:
            if not reference["anchor"]:
                continue
            mapped = url_index.get(reference["page_url"])
            if mapped:
                anchor_ids.update(
                    mapped["anchor_document_ids"].get(reference["anchor"], set())
                )
        owner = answer.get("owner") or {}
        candidates.append(
            {
                "case_id": question["case_id"],
                "question": question["question"],
                "source_url": question["source_url"],
                "source_tags": question["source_tags"],
                "accepted_answer_id": answer["answer_id"],
                "accepted_answer_url": f'https://stackoverflow.com/a/{answer["answer_id"]}',
                "accepted_answer_author": html.unescape(
                    owner.get("display_name", "deleted user")
                ),
                "accepted_answer_author_url": owner.get("link", ""),
                "accepted_answer_content_license": answer.get("content_license", ""),
                "official_document_urls": links,
                "official_document_references": references,
                "candidate_document_ids": sorted(mapped_ids),
                "anchor_candidate_document_ids": sorted(anchor_ids),
                "anchor_mapping_status": (
                    "single_candidate"
                    if len(anchor_ids) == 1
                    else "multiple_candidates"
                    if anchor_ids
                    else "not_mapped"
                ),
                "candidate_source_paths": sorted(mapped_paths),
                "review_status": "pending",
                "label_status": "external_link_requires_human_section_audit",
            }
        )
    return sorted(candidates, key=lambda item: item["case_id"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--pilot", type=Path, default=DEFAULT_PILOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/private/tmp/kubernetes-accepted-answer-cache"),
    )
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if args.request_delay < 0:
        raise ValueError("request delay cannot be negative")

    output_path = args.output_dir / "accepted_answer_doc_links.json"
    if output_path.exists() and not args.rebuild:
        raise SystemExit("bootstrap output exists; pass --rebuild to replace it")
    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    documents = json.loads(args.knowledge.read_text(encoding="utf-8"))
    pilot = json.loads(args.pilot.read_text(encoding="utf-8"))
    pilot_case_ids = {row["case_id"] for row in pilot}
    answer_ids = sorted(
        question["accepted_answer_id"]
        for question in questions
        if question.get("accepted_answer_id")
    )
    answers, quota_remaining = fetch_answers(answer_ids, args.cache_dir, args.request_delay)
    candidates = build_candidates(
        questions,
        answers,
        pilot_case_ids,
        corpus_url_index(documents),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidate_bytes = encoded(candidates)
    output_path.write_bytes(candidate_bytes)
    manifest = {
        "role": "benchmark_bootstrap_candidates_not_ground_truth",
        "method": "accepted_answer_explicit_official_document_link",
        "question_count": len(questions),
        "pilot_excluded_count": sum(
            question["case_id"] in pilot_case_ids for question in questions
        ),
        "answer_count": len(answers),
        "official_link_candidate_count": len(candidates),
        "corpus_mapped_candidate_count": sum(
            bool(candidate["candidate_document_ids"]) for candidate in candidates
        ),
        "quota_remaining": quota_remaining,
        "hosted_model_calls": 0,
        "answer_bodies_redistributed": False,
        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "questions_sha256": hashlib.sha256(args.questions.read_bytes()).hexdigest(),
        "knowledge_sha256": hashlib.sha256(args.knowledge.read_bytes()).hexdigest(),
        "pilot_sha256": hashlib.sha256(args.pilot.read_bytes()).hexdigest(),
        "single_anchor_candidate_count": sum(
            candidate["anchor_mapping_status"] == "single_candidate"
            for candidate in candidates
        ),
        "review_policy": (
            "External accepted-answer links are candidate evidence only. A human must "
            "confirm the exact official section before any evaluation label is created."
        ),
    }
    (args.output_dir / "manifest.json").write_bytes(encoded(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
