#!/usr/bin/env python3
"""Collect attributed Kubernetes question metadata through Stack Exchange API."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from support_copilot.medusa_discussions import near_duplicate, normalize_text


API_URL = "https://api.stackexchange.com/2.3/search/advanced"
USER_AGENT = "ai-support-copilot-benchmark/0.1 (attributed public research collector)"
WORD = re.compile(r"[a-z0-9]+", re.I)


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def api_url(from_date: date, accepted: bool, page: int) -> str:
    return API_URL + "?" + urllib.parse.urlencode(
        {
            "site": "stackoverflow",
            "tagged": "kubernetes",
            "accepted": str(accepted).lower(),
            "fromdate": int(
                datetime.combine(from_date, datetime.min.time(), timezone.utc).timestamp()
            ),
            "order": "desc",
            "sort": "creation",
            "pagesize": 100,
            "page": page,
        }
    )


def fetch(url: str, path: Path, delay: float) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if delay:
        time.sleep(delay)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(payload))
    if payload.get("backoff"):
        time.sleep(float(payload["backoff"]))
    return payload


def candidate_from_item(item: dict) -> dict | None:
    title = normalize_text(html.unescape(item.get("title", "")))
    if not (20 <= len(title) <= 220 and len(WORD.findall(title)) >= 4):
        return None
    if item.get("closed_date"):
        return None
    owner = item.get("owner") or {}
    created = datetime.fromtimestamp(item["creation_date"], timezone.utc)
    activity = datetime.fromtimestamp(item["last_activity_date"], timezone.utc)
    return {
        "case_id": f"stackoverflow-kubernetes-{item['question_id']}",
        "question_id": item["question_id"],
        "question": title,
        "source_url": item["link"],
        "source_type": "stackoverflow_question",
        "source_created_at": created.isoformat().replace("+00:00", "Z"),
        "source_last_activity_at": activity.isoformat().replace("+00:00", "Z"),
        "source_tags": sorted(item.get("tags", [])),
        "score": item.get("score", 0),
        "view_count": item.get("view_count", 0),
        "answer_count": item.get("answer_count", 0),
        "accepted_answer_id": item.get("accepted_answer_id"),
        "author_display_name": html.unescape(owner.get("display_name", "deleted user")),
        "author_url": owner.get("link", ""),
        "content_license": item.get("content_license", ""),
        "label_status": "unlabelled_candidate",
    }


def collect(
    accepted: bool,
    from_date: date,
    pages: int,
    cache_dir: Path,
    delay: float,
) -> tuple[list[dict], dict]:
    candidates = []
    request_count = 0
    quota_remaining = None
    for page in range(1, pages + 1):
        url = api_url(from_date, accepted, page)
        request_digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        payload = fetch(
            url,
            cache_dir
            / ("accepted" if accepted else "challenge")
            / f"page-{page}-{request_digest}.json",
            delay,
        )
        request_count += 1
        quota_remaining = payload.get("quota_remaining", quota_remaining)
        for item in payload.get("items", []):
            candidate = candidate_from_item(item)
            if candidate is None:
                continue
            if any(near_duplicate(candidate["question"], row["question"], 0.82) for row in candidates):
                continue
            candidates.append(candidate)
        if not payload.get("has_more", False):
            break
    return candidates, {
        "request_count": request_count,
        "quota_remaining": quota_remaining,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("/private/tmp/kubernetes-stackoverflow-cache"))
    parser.add_argument("--from-date", type=date.fromisoformat, default=date(2025, 1, 1))
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if args.pages <= 0 or args.request_delay < 0:
        raise ValueError("pages must be positive and request delay cannot be negative")

    accepted_path = args.output_dir / "accepted_questions.json"
    challenge_path = args.output_dir / "challenge_questions.json"
    if (accepted_path.exists() or challenge_path.exists()) and not args.rebuild:
        raise SystemExit("Kubernetes question pool already exists; pass --rebuild to replace")

    accepted, accepted_meta = collect(
        True, args.from_date, args.pages, args.cache_dir, args.request_delay
    )
    challenge, challenge_meta = collect(
        False, args.from_date, args.pages, args.cache_dir, args.request_delay
    )
    accepted_ids = {row["case_id"] for row in accepted}
    challenge = [row for row in challenge if row["case_id"] not in accepted_ids]
    if len(accepted) < 100 or len(challenge) < 100:
        raise ValueError(
            f"insufficient authentic questions: accepted={len(accepted)}, challenge={len(challenge)}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    accepted_bytes = encoded(accepted)
    challenge_bytes = encoded(challenge)
    accepted_path.write_bytes(accepted_bytes)
    challenge_path.write_bytes(challenge_bytes)
    manifest = {
        "source": API_URL,
        "site": "stackoverflow",
        "tag": "kubernetes",
        "from_date": args.from_date.isoformat(),
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "accepted_count": len(accepted),
        "challenge_count": len(challenge),
        "accepted_sha256": hashlib.sha256(accepted_bytes).hexdigest(),
        "challenge_sha256": hashlib.sha256(challenge_bytes).hexdigest(),
        "accepted_request_metadata": accepted_meta,
        "challenge_request_metadata": challenge_meta,
        "content_policy": (
            "Question titles and attribution metadata only; bodies and answers are not "
            "redistributed. Each row preserves its source URL and content license."
        ),
        "label_policy": "Authentic candidates only; no evaluation or AI label is included.",
    }
    (args.output_dir / "manifest.json").write_bytes(encoded(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
