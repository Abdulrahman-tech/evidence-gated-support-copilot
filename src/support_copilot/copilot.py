"""Retrieval-grounded support drafting with mandatory human review signals."""

import logging
from collections.abc import Callable

from support_copilot.evidence import (
    EvidenceDecision,
    EvidenceVerifier,
    FailClosedEvidenceVerifier,
    validate_verification,
)
from support_copilot.knowledge import (
    DEFAULT_MINIMUM_SCORE,
    DEFAULT_MINIMUM_SCORE_RATIO,
    KnowledgeBase,
    retrieval_is_confident,
)
from support_copilot.models import DraftResponse, SearchResult
from support_copilot.safety import detect_prompt_injection
from support_copilot.scope import ScopeRouter, router_for_tenant


AnswerGenerator = Callable[[str, list[SearchResult]], str]
LOGGER = logging.getLogger("support_copilot.evidence")
TEMPORARY_VERIFIER_ERRORS = {
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "RateLimitError",
    "ServiceUnavailableError",
}


def verification_failure_reason(error: Exception) -> tuple[str, str]:
    """Return a safe operational category and user-facing review reason."""

    if type(error).__name__ in TEMPORARY_VERIFIER_ERRORS:
        return "provider_unavailable", "evidence verifier temporarily unavailable"
    return "invalid_response", "invalid evidence verification response"


def extractive_answer(ticket: str, evidence: list[SearchResult]) -> str:
    """Create a deterministic offline draft; replace with an LLM behind this interface."""

    del ticket
    if not evidence:
        return "I could not find enough approved information to draft an answer."
    statements = " ".join(result.passage for result in evidence)
    return f"Based on the support documentation: {statements}"


class SupportCopilot:
    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        generator: AnswerGenerator = extractive_answer,
        minimum_score: float = DEFAULT_MINIMUM_SCORE,
        minimum_score_ratio: float = DEFAULT_MINIMUM_SCORE_RATIO,
        tenant_id: str | None = None,
        evidence_verifier: EvidenceVerifier | None = None,
        scope_router: ScopeRouter | None = None,
    ) -> None:
        self.knowledge_base = knowledge_base
        self.generator = generator
        self.minimum_score = minimum_score
        self.minimum_score_ratio = minimum_score_ratio
        self.tenant_id = tenant_id
        self.evidence_verifier = evidence_verifier or FailClosedEvidenceVerifier()
        self.scope_router = scope_router or router_for_tenant(tenant_id)

    def draft(self, ticket: str, limit: int = 3) -> DraftResponse:
        if not ticket.strip():
            raise ValueError("ticket cannot be empty")

        scope_route = (
            self.scope_router.route(ticket) if self.scope_router is not None else None
        )
        if scope_route is not None and not scope_route.in_scope:
            reason = (
                f"requires {scope_route.display_name} documentation outside the pinned "
                "Kubernetes core corpus"
            )
            return DraftResponse(
                answer=(
                    "I cannot answer this from the pinned Kubernetes core documentation. "
                    f"This question appears to require {scope_route.display_name} documentation."
                ),
                citations=(),
                needs_human_review=True,
                review_reasons=(reason,),
                evidence_decision=EvidenceDecision.UNSUPPORTED.value,
                scope_route=scope_route.name,
                trajectory=(
                    f"scope:{scope_route.name}",
                    "retrieval:skipped",
                    "safety:skipped",
                    "evidence:skipped",
                    "response:routed_abstention",
                ),
            )

        candidates = self.knowledge_base.search(
            ticket,
            limit=max(limit, 2),
            tenant_id=self.tenant_id,
        )
        reasons = list(detect_prompt_injection(ticket))
        reasons.extend(
            reason
            for result in candidates
            for reason in detect_prompt_injection(result.passage)
        )
        evidence_decision = EvidenceDecision.UNCERTAIN
        trajectory = [
            f"scope:{scope_route.name if scope_route else 'configured_corpus'}",
            (
                "retrieval:empty"
                if not candidates
                else "retrieval:confident"
                if retrieval_is_confident(
                    candidates,
                    minimum_score=self.minimum_score,
                    minimum_score_ratio=self.minimum_score_ratio,
                )
                else "retrieval:low_confidence"
            ),
            "safety:blocked" if reasons else "safety:passed",
        ]
        if reasons:
            citations = ()
            trajectory.append("evidence:skipped")
        elif not candidates:
            reasons.append("insufficient retrieval confidence")
            citations = ()
            trajectory.append("evidence:skipped")
        elif not retrieval_is_confident(
            candidates,
            minimum_score=self.minimum_score,
            minimum_score_ratio=self.minimum_score_ratio,
        ):
            reasons.append("low retrieval confidence")
            citations = ()
            trajectory.append("evidence:skipped")
        else:
            eligible_candidates = candidates[:limit]
            try:
                verification = self.evidence_verifier.verify(
                    ticket,
                    eligible_candidates,
                )
                evidence_decision = verification.decision
                citations = validate_verification(verification, eligible_candidates)
            except Exception as error:
                failure_category, failure_reason = verification_failure_reason(error)
                LOGGER.warning(
                    "evidence verification failed: category=%s error_type=%s",
                    failure_category,
                    type(error).__name__,
                )
                evidence_decision = EvidenceDecision.UNCERTAIN
                citations = ()
                reasons.append(failure_reason)
                trajectory.append(f"evidence:{failure_category}")
            else:
                trajectory.append(f"evidence:{verification.decision.value}")
                if verification.decision is EvidenceDecision.UNSUPPORTED:
                    reasons.append("official documentation does not directly answer the question")
                elif verification.decision is EvidenceDecision.UNCERTAIN:
                    reasons.append(
                        verification.reason or "evidence verification was inconclusive"
                    )

        answer = self.generator(ticket, list(citations))
        trajectory.append("response:cited" if citations else "response:abstained")
        return DraftResponse(
            answer=answer,
            citations=citations,
            needs_human_review=True,
            review_reasons=tuple(dict.fromkeys(reasons)),
            evidence_decision=evidence_decision.value,
            scope_route=(scope_route.name if scope_route else "configured_corpus"),
            trajectory=tuple(trajectory),
        )
