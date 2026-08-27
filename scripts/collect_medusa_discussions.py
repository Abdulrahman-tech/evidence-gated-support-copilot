#!/usr/bin/env python3
"""Collect answered Medusa Q&A metadata with reproducible local caching."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from support_copilot.medusa_discussions import (
    DiscussionQuestion,
    deduplicate_discussions,
    extract_answered_discussion,
    extract_discussion_links,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
LISTING_URL = (
    "https://github.com/medusajs/medusa/discussions/categories/q-a"
    "?discussions_q=category%3AQ%26A+is%3Aanswered&page={page}"
)
USER_AGENT = "ai-support-copilot-benchmark/0.1 (public research collector)"


def fetch(url: str, path: Path, refresh: bool = False) -> str:
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = response.read().decode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return payload


def fetch_discussion(
    number: int,
    cache_dir: Path,
    refresh: bool,
) -> DiscussionQuestion | None:
    path = cache_dir / "discussions" / f"{number}.html"
    url = f"https://github.com/medusajs/medusa/discussions/{number}"
    page = fetch(url, path, refresh=refresh)
    return extract_answered_discussion(page, number)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/private/tmp/medusa-discussions-cache"),
    )
    parser.add_argument("--listing-pages", type=int, default=5)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--output",
        type=Path,
        help="Write a separate source pool instead of replacing the canonical 100-case file.",
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    canonical_output = DATA / "discussion_sources.json"
    output = args.output or canonical_output
    if output.exists() and not args.rebuild:
        raise SystemExit("discussion sources already exist; pass --rebuild to replace")
    output.parent.mkdir(parents=True, exist_ok=True)

    links: dict[int, str] = {}
    for page_number in range(1, args.listing_pages + 1):
        page = fetch(
            LISTING_URL.format(page=page_number),
            args.cache_dir / "listings" / f"page-{page_number}.html",
            refresh=args.refresh,
        )
        previous_count = len(links)
        links.update(extract_discussion_links(page))
        if len(links) == previous_count:
            print(f"stopped at listing page {page_number}; no new discussions", flush=True)
            break

    questions: list[DiscussionQuestion] = []
    failures: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(fetch_discussion, number, args.cache_dir, args.refresh): number
            for number in links
        }
        for completed, future in enumerate(as_completed(futures), 1):
            number = futures[future]
            try:
                question = future.result()
                if question:
                    questions.append(question)
                else:
                    failures[number] = "missing accepted QAPage answer"
            except Exception as error:  # network errors are recorded for a reproducible retry
                failures[number] = f"{type(error).__name__}: {error}"
            if completed % 20 == 0:
                print(f"processed {completed}/{len(futures)} discussions", flush=True)
            time.sleep(0.02)

    unique, duplicates = deduplicate_discussions(questions)
    payload = [
        {
            "case_id": f"medusa-discussion-{question.number}",
            "source_url": question.source_url,
            "question": question.title,
            "source_category": "Q&A",
            "source_answered": True,
            "accepted_answer_url": question.accepted_answer_url,
            "question_word_count": question.question_word_count,
            "answer_word_count": question.answer_word_count,
            "question_text_sha256": question.question_text_sha256,
            "accepted_answer_text_sha256": question.accepted_answer_text_sha256,
            "accepted_answer_official_document_urls": list(
                question.accepted_answer_official_document_urls
            ),
        }
        for question in unique
        if 20 <= len(question.title) <= 220 and len(question.title.split()) >= 4
    ]
    output_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    output.write_bytes(output_bytes)

    collection_metadata = {
            "discussion_listing_source": LISTING_URL.format(page=1),
            "discussion_listing_pages_requested": args.listing_pages,
            "discussion_link_count": len(links),
            "discussion_answered_count": len(questions),
            "discussion_candidate_count": len(payload),
            "discussion_duplicate_count": len(duplicates),
            "discussion_failure_count": len(failures),
            "discussion_official_document_link_count": sum(
                bool(row["accepted_answer_official_document_urls"])
                for row in payload
            ),
            "discussion_sources_sha256": hashlib.sha256(output_bytes).hexdigest(),
            "discussion_content_policy": (
                "Titles, source URLs, accepted-answer URLs, word counts, and content "
                "hashes only; discussion bodies and answers remain in the local cache."
            ),
        }
    if output.resolve() == canonical_output.resolve():
        manifest_path = DATA / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(collection_metadata)
        manifest_path.write_bytes(
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        )
    else:
        (output.parent / "collection_manifest.json").write_text(
            json.dumps(collection_metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    report = {
        "listing_links": len(links),
        "answered_parsed": len(questions),
            "usable_unique": len(payload),
        "with_official_document_links": sum(
            bool(row["accepted_answer_official_document_urls"])
            for row in payload
        ),
        "duplicates": duplicates,
        "failures": failures,
    }
    (args.cache_dir / "collection-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: value for key, value in report.items() if key not in {"duplicates", "failures"}}))


if __name__ == "__main__":
    main()
