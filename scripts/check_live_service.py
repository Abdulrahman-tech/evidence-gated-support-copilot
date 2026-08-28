#!/usr/bin/env python3
"""Fail closed when the public service's operational contract is broken."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping


REQUIRED_SECURITY_HEADERS = {
    "cache-control": "no-store",
    "content-security-policy": "frame-ancestors 'none'",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}
REQUIRED_METRICS = (
    "support_copilot_http_requests_total",
    "support_copilot_http_errors_total",
    "support_copilot_http_request_duration_seconds_sum",
    "support_copilot_drafts_supported_total",
    "support_copilot_drafts_abstained_total",
    "support_copilot_draft_failures_total",
    "support_copilot_rate_limited_total",
)


def fetch(url: str, timeout: float) -> tuple[str, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "support-copilot-live-monitor/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        headers = {name.lower(): value for name, value in response.headers.items()}
    return body, headers


def validate_probe(
    health: Mapping[str, object],
    readiness: Mapping[str, object],
    metrics: str,
    headers: Mapping[str, str],
) -> list[str]:
    failures: list[str] = []
    if health != {"status": "ok"}:
        failures.append("health contract failed")
    if readiness.get("status") != "ready":
        failures.append("readiness contract failed")
    if not readiness.get("evidence_verifier"):
        failures.append("readiness omitted evidence verifier")
    for name, expected_fragment in REQUIRED_SECURITY_HEADERS.items():
        if expected_fragment not in headers.get(name, ""):
            failures.append(f"missing or invalid security header: {name}")
    for metric_name in REQUIRED_METRICS:
        if metric_name not in metrics:
            failures.append(f"missing metric: {metric_name}")
    for forbidden_label in ('tenant="', 'api_key="', 'ticket="'):
        if forbidden_label in metrics.lower():
            failures.append(
                f"sensitive metric label detected: {forbidden_label.split('=', 1)[0]}"
            )
    return failures


def probe(base_url: str, timeout: float) -> list[str]:
    base = base_url.rstrip("/")
    health_body, _ = fetch(f"{base}/healthz", timeout)
    readiness_body, _ = fetch(f"{base}/readyz", timeout)
    metrics, headers = fetch(f"{base}/metrics", timeout)
    return validate_probe(
        json.loads(health_body),
        json.loads(readiness_body),
        metrics,
        headers,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="https://evidence-gated-support-copilot.onrender.com",
    )
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--retry-delay", type=float, default=10)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    if args.attempts <= 0 or args.retry_delay < 0 or args.timeout <= 0:
        parser.error("attempts and timeout must be positive; retry-delay cannot be negative")

    last_error = "monitor did not run"
    for attempt in range(1, args.attempts + 1):
        try:
            failures = probe(args.base_url, args.timeout)
            if not failures:
                print(
                    json.dumps(
                        {"status": "passed", "attempt": attempt},
                        separators=(",", ":"),
                    )
                )
                return 0
            last_error = "; ".join(failures)
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
            last_error = f"{type(error).__name__}: {error}"
        if attempt < args.attempts:
            time.sleep(args.retry_delay)
    print(
        json.dumps(
            {"status": "failed", "reason": last_error},
            separators=(",", ":"),
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
