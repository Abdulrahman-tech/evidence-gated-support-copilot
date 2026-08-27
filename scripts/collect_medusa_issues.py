#!/usr/bin/env python3
"""Collect public Medusa issue metadata into a non-labelled candidate pool."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from support_copilot.medusa_discussions import near_duplicate, normalize_text


API_URL = (
    "https://api.github.com/repos/medusajs/medusa/issues"
    "?state={state}&per_page={per_page}&page={page}&sort=created&direction=desc"
)
USER_AGENT = "ai-support-copilot-benchmark/0.1 (public research collector)"
PREFIX = re.compile(r"^\s*\[(?:bug|feature|improvement)]\s*:\s*", re.I)
WORD = re.compile(r"[a-z0-9]+", re.I)


def fetch_page(url: str, cache_path: Path, refresh: bool) -> list[dict]:
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def usable_title(value: str) -> str | None:
    title = normalize_text(PREFIX.sub("", value))
    words = WORD.findall(title)
    if not (20 <= len(title) <= 220 and len(words) >= 4):
        return None
    if not any(character.isalpha() for character in title):
        return None
    return title


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/private/tmp/medusa-issues-cache"),
    )
    parser.add_argument("--pages", type=int, default=30)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--state", choices=("all", "open", "closed"), default="all")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.rebuild:
        raise SystemExit("issue source pool already exists; pass --rebuild to replace")
    if not 1 <= args.per_page <= 100 or args.pages <= 0:
        raise ValueError("pages must be positive and per-page must be between 1 and 100")

    raw_items: dict[int, dict] = {}
    pages_fetched = 0
    for page in range(1, args.pages + 1):
        try:
            items = fetch_page(
                API_URL.format(state=args.state, per_page=args.per_page, page=page),
                args.cache_dir / args.state / f"page-{page}.json",
                args.refresh,
            )
        except urllib.error.HTTPError as error:
            if error.code == 422 and page > 10:
                print("stopped at GitHub's 1,000-result pagination window", flush=True)
                break
            raise
        pages_fetched += 1
        if not items:
            break
        for item in items:
            if "pull_request" not in item:
                raw_items[item["number"]] = item
        print(
            f"processed issue page {page}/{args.pages}; issues={len(raw_items)}",
            flush=True,
        )
        time.sleep(0.1)

    candidates = []
    duplicate_count = 0
    for number, item in sorted(raw_items.items(), reverse=True):
        question = usable_title(item.get("title", ""))
        if question is None:
            continue
        duplicate = next(
            (
                candidate
                for candidate in candidates
                if near_duplicate(question, candidate["question"])
            ),
            None,
        )
        if duplicate:
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
    payload = (json.dumps(candidates, indent=2, sort_keys=True) + "\n").encode()
    args.output.write_bytes(payload)
    manifest = {
        "source": API_URL.format(state=args.state, per_page=args.per_page, page=1),
        "state_filter": args.state,
        "pages_requested": args.pages,
        "pages_fetched": pages_fetched,
        "raw_issue_count": len(raw_items),
        "usable_unique_count": len(candidates),
        "near_duplicate_count": duplicate_count,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "content_policy": (
            "Public issue titles, URLs, labels, timestamps, word counts, and body "
            "hashes only; issue bodies are not redistributed in the candidate pool."
        ),
    }
    (args.output.parent / "issue_collection_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
