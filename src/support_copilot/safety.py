"""Conservative checks for untrusted support tickets and retrieved content."""

import re


INJECTION_PATTERNS = (
    re.compile(r"ignore (all |any )?(previous|prior|system) instructions", re.I),
    re.compile(r"reveal (the )?(system prompt|api key|secret)", re.I),
    re.compile(r"act as (an? )?(administrator|system|developer)", re.I),
)


def detect_prompt_injection(text: str) -> tuple[str, ...]:
    reasons = []
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            reasons.append("possible prompt-injection language detected")
            break
    return tuple(reasons)
