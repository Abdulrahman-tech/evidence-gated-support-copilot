"""Explicit release gates for a production support-retrieval candidate."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessGate:
    name: str
    passed: bool
    observed: str
    required: str


def maximum_gap_gate(
    name: str,
    development_value: float,
    validation_value: float,
    maximum_gap: float,
) -> ReadinessGate:
    gap = abs(development_value - validation_value)
    return ReadinessGate(
        name=name,
        passed=gap <= maximum_gap,
        observed=f"{gap:.3f}",
        required=f"<= {maximum_gap:.3f}",
    )


def minimum_gate(
    name: str,
    observed: float,
    minimum: float,
) -> ReadinessGate:
    return ReadinessGate(
        name=name,
        passed=observed >= minimum,
        observed=f"{observed:.3f}",
        required=f">= {minimum:.3f}",
    )
