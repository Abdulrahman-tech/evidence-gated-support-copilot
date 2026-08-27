#!/usr/bin/env python3
"""Collect older Medusa issue-only history through bounded GitHub search windows."""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from support_copilot.medusa_discussions import near_duplicate, normalize_text


SEARCH_URL = "https://api.github.com/search/issues"
USER_AGENT = "ai-support-copilot-benchmark/0.1 (public research collector)"
PREFIX = re.compile(r"^\s*\[(?:bug|feature|improvement)]\s*:\s*", re.I)
WORD = re.compile(r"[a-z0-9]+", re.I)


def month_windows(start: date, end: date) -> list[tuple[date, date]]:
    windows = []
    year, month = end.year, end.month
    while (year, month) >= (start.year, start.month):
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        windows.append((max(first, start), min(last, end)))
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return windows


def fetch(url: str, cache_path: Path, delay: float) -> dict:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    if delay:
        time.sleep(delay)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in {403, 429}:
            raise RuntimeError(
                "GitHub search rate limit reached; rerun later to resume from cache"
            ) from error
        raise
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def search_url(start: date, end: date, page: int) -> str:
    query = (
        f"repo:medusajs/medusa is:issue "
        f"created:{start.isoformat()}..{end.isoformat()}"
    )
    return SEARCH_URL + "?" + urllib.parse.urlencode(
        {"q": query, "sort": "created", "order": "desc", "per_page": 100, "page": page}
    )


def usable_title(value: str) -> str | None:
    title = normalize_text(PREFIX.sub("", value))
    words = WORD.findall(title)
    if not (20 <= len(title) <= 220 and len(words) >= 4):
        return None
    return title if any(character.isalpha() for character in title) else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/private/tmp/medusa-issue-history-cache"),
    )
    parser.add_argument("--start", type=date.fromisoformat, default=date(2018, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--target", type=int, default=1_200)
    parser.add_argument("--request-delay", type=float, default=6.5)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.rebuild:
        raise SystemExit("issue history already exists; pass --rebuild to replace")
    if args.start > args.end or args.target <= 0 or args.request_delay < 0:
        raise ValueError("invalid date range, target, or request delay")

    raw_items: dict[int, dict] = {}
    request_count = 0
    for first, last in month_windows(args.start, args.end):
        cache_base = args.cache_dir / f"{first:%Y-%m}"
        first_page = fetch(search_url(first, last, 1), cache_base / "page-1.json", args.request_delay)
        request_count += 1
        total = first_page["total_count"]
        if total > 1_000:
            raise ValueError(f"monthly search window exceeds 1,000 results: {first:%Y-%m}")
        pages = max(1, math.ceil(total / 100))
        payloads = [first_page]
        for page in range(2, pages + 1):
            payloads.append(
                fetch(search_url(first, last, page), cache_base / f"page-{page}.json", args.request_delay)
            )
            request_count += 1
        for payload in payloads:
            for item in payload["items"]:
                raw_items[item["number"]] = item
        print(
            f"processed {first:%Y-%m}: reported={total}, unique_issues={len(raw_items)}",
            flush=True,
        )
        if len(raw_items) >= args.target:
            break

    candidates = []
    duplicate_count = 0
    for number, item in sorted(raw_items.items(), reverse=True):
        question = usable_title(item.get("title", ""))
        if question is None:
            continue
        if any(near_duplicate(question, existing["question"]) for existing in candidates):
            duplicate_count += 1
            continue
        body = normalize_text(item.get("body") or "")
        candidates.append(
            {
                "case_id": f"medusa-issue-{number}",
                "question": question,
                "source_url": item["html_url"],
                "source_type": "github_issue_report",
                "source_repository": "medusajs/medusa",
                "source_state": item["state"],
                "source_created_at": item["created_at"],
                "source_updated_at": item["updated_at"],
                "source_labels": sorted(label["name"] for label in item["labels"]),
                "body_word_count": len(body.split()),
                "body_text_sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_bytes = (json.dumps(candidates, indent=2, sort_keys=True) + "\n").encode()
    args.output.write_bytes(output_bytes)
    manifest = {
        "source": SEARCH_URL,
        "query": "repo:medusajs/medusa is:issue created:<monthly-window>",
        "requested_start": args.start.isoformat(),
        "requested_end": args.end.isoformat(),
        "raw_unique_issue_count": len(raw_items),
        "usable_unique_count": len(candidates),
        "near_duplicate_count": duplicate_count,
        "request_count": request_count,
        "sha256": hashlib.sha256(output_bytes).hexdigest(),
        "content_policy": (
            "Public issue titles, URLs, labels, timestamps, word counts, and body "
            "hashes only; issue bodies are not redistributed in the candidate pool."
        ),
    }
    (args.output.parent / "issue_history_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
