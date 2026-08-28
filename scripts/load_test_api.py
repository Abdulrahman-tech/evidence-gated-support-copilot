#!/usr/bin/env python3
"""Run a bounded, non-confidential load check against the draft API."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


DEFAULT_TICKET = (
    "Which Kubernetes Service type is reachable only from within the cluster?"
)


@dataclass(frozen=True)
class Result:
    status_code: int
    duration_seconds: float
    evidence_decision: str | None


def validate_base_url(base_url: str, allow_remote: bool) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base URL must be an absolute HTTP(S) URL")
    if not allow_remote and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("remote load tests require --allow-remote")
    return base_url.rstrip("/")


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return ordered[index]


def send_request(
    base_url: str,
    api_key: str,
    request_number: int,
    timeout: float,
) -> Result:
    body = json.dumps({"ticket": DEFAULT_TICKET, "limit": 3}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/v1/drafts",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "support-copilot-load-check/1.0",
            "X-Request-ID": f"load-check:{request_number}",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return Result(
                response.status,
                time.monotonic() - started,
                payload.get("evidence_decision"),
            )
    except urllib.error.HTTPError as error:
        return Result(error.code, time.monotonic() - started, None)
    except (OSError, ValueError, json.JSONDecodeError):
        return Result(0, time.monotonic() - started, None)


def summarize(results: list[Result]) -> dict[str, object]:
    successful = [result for result in results if result.status_code == 200]
    status_counts: dict[str, int] = {}
    for result in results:
        key = str(result.status_code)
        status_counts[key] = status_counts.get(key, 0) + 1
    return {
        "requests": len(results),
        "successful": len(successful),
        "error_rate": (
            (len(results) - len(successful)) / len(results) if results else 1.0
        ),
        "p95_seconds": percentile(
            [result.duration_seconds for result in results],
            0.95,
        ),
        "status_counts": status_counts,
        "supported": sum(
            result.evidence_decision == "supported" for result in successful
        ),
        "abstained": sum(
            result.evidence_decision != "supported" for result in successful
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--max-p95-seconds", type=float, default=2)
    parser.add_argument("--max-error-rate", type=float, default=0)
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()
    if args.requests <= 0 or args.concurrency <= 0 or args.timeout <= 0:
        parser.error("requests, concurrency, and timeout must be positive")
    if args.max_p95_seconds <= 0 or not 0 <= args.max_error_rate <= 1:
        parser.error("invalid pass thresholds")
    base_url = validate_base_url(args.base_url, args.allow_remote)
    api_key = os.environ.get("SUPPORT_COPILOT_LOAD_TEST_API_KEY")
    if not api_key:
        parser.error("SUPPORT_COPILOT_LOAD_TEST_API_KEY is required")

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.concurrency
    ) as executor:
        results = list(
            executor.map(
                lambda number: send_request(base_url, api_key, number, args.timeout),
                range(args.requests),
            )
        )
    summary = summarize(results)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    passed = (
        summary["error_rate"] <= args.max_error_rate
        and summary["p95_seconds"] <= args.max_p95_seconds
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
