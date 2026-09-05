"""Small, reproducible retrieval evaluation harness."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from support_copilot.evidence import EvidenceDecision, EvidenceVerification
from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident


@dataclass(frozen=True)
class EvaluationCase:
    question: str
    expected_document_id: str | None
    category: str = "direct"
    difficulty: str = "medium"
    provenance: str = "synthetic"
    source_conversation_id: str = ""
    source_tweet_id: str = ""
    adjudication: dict | None = None
    case_id: str = ""
    tenant_id: str = ""
    source_type: str = ""
    source_url: str = ""
    review_method: str = ""
    review_batch: str = ""
    review_notes: str = ""
    source_question_sha256: str = ""
    source_word_count: int = 0


@dataclass(frozen=True)
class SelectiveRiskPoint:
    minimum_score: float
    coverage: float
    risk: float


@dataclass(frozen=True)
class EvidenceVerificationMetrics:
    supported_precision: float
    supported_recall: float
    unsupported_abstention_rate: float


def load_cases(path: Path) -> list[EvaluationCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [EvaluationCase(**item) for item in payload]


def evidence_verification_metrics(
    cases: list[EvaluationCase],
    predictions: list[EvidenceVerification],
) -> EvidenceVerificationMetrics:
    if len(cases) != len(predictions):
        raise ValueError("cases and evidence predictions must have equal lengths")
    supported_cases = sum(case.expected_document_id is not None for case in cases)
    unsupported_cases = len(cases) - supported_cases
    supported_predictions = 0
    correct_supported_predictions = 0
    unsupported_abstentions = 0
    for case, prediction in zip(cases, predictions, strict=True):
        if prediction.decision is EvidenceDecision.SUPPORTED:
            supported_predictions += 1
            claimed_ids = {claim.document_id for claim in prediction.claims}
            if case.expected_document_id in claimed_ids:
                correct_supported_predictions += 1
        elif case.expected_document_id is None:
            unsupported_abstentions += 1
    return EvidenceVerificationMetrics(
        supported_precision=(
            correct_supported_predictions / supported_predictions
            if supported_predictions
            else 0.0
        ),
        supported_recall=(
            correct_supported_predictions / supported_cases if supported_cases else 0.0
        ),
        unsupported_abstention_rate=(
            unsupported_abstentions / unsupported_cases if unsupported_cases else 0.0
        ),
    )


def retrieval_recall_at_k(
    knowledge_base: KnowledgeBase,
    cases: list[EvaluationCase],
    k: int = 3,
    minimum_score: float = 0.0,
    minimum_score_ratio: float = 1.0,
) -> float:
    supported = [case for case in cases if case.expected_document_id is not None]
    if not supported:
        raise ValueError("evaluation requires at least one supported case")
    hits = 0
    for case in supported:
        results = knowledge_base.search(case.question, limit=max(k, 2))
        if retrieval_is_confident(results, minimum_score, minimum_score_ratio) and any(
            result.document_id == case.expected_document_id for result in results[:k]
        ):
            hits += 1
    return hits / len(supported)


def unsupported_abstention_rate(
    knowledge_base: KnowledgeBase,
    cases: list[EvaluationCase],
    minimum_score: float = 0.0,
    minimum_score_ratio: float = 1.0,
) -> float:
    unsupported = [case for case in cases if case.expected_document_id is None]
    if not unsupported:
        raise ValueError("evaluation requires at least one unsupported case")
    abstentions = 0
    for case in unsupported:
        results = knowledge_base.search(case.question, limit=2)
        if not retrieval_is_confident(results, minimum_score, minimum_score_ratio):
            abstentions += 1
    return abstentions / len(unsupported)


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("successes and total must describe a non-empty binomial sample")
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return center - radius, center + radius


def selective_risk_curve(
    knowledge_base: KnowledgeBase,
    cases: list[EvaluationCase],
    minimum_scores: tuple[float, ...],
    minimum_score_ratio: float = 1.0,
) -> list[SelectiveRiskPoint]:
    ranked = [
        (case, knowledge_base.search(case.question, limit=2))
        for case in cases
    ]
    points = []
    for minimum_score in minimum_scores:
        accepted = 0
        errors = 0
        for case, results in ranked:
            if not retrieval_is_confident(
                results, minimum_score, minimum_score_ratio
            ):
                continue
            accepted += 1
            if (
                case.expected_document_id is None
                or results[0].document_id != case.expected_document_id
            ):
                errors += 1
        points.append(
            SelectiveRiskPoint(
                minimum_score=minimum_score,
                coverage=accepted / len(cases),
                risk=errors / accepted if accepted else 0.0,
            )
        )
    return points
