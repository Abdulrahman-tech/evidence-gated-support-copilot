"""Authenticated HTTP boundary for the support copilot."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from support_copilot.copilot import SupportCopilot
from support_copilot.evidence import EvidenceVerifier, FailClosedEvidenceVerifier
from support_copilot.evidence import LocalOverlapEvidenceVerifier
from support_copilot.demo import DEMO_HTML
from support_copilot.groq_evidence import DEFAULT_GROQ_MODEL, GroqEvidenceVerifier
from support_copilot.knowledge import (
    DEFAULT_MINIMUM_SCORE,
    DEFAULT_MINIMUM_SCORE_RATIO,
    KnowledgeBase,
)
from support_copilot.models import KnowledgeDocument
from support_copilot.openai_evidence import OpenAIEvidenceVerifier


LOGGER = logging.getLogger("support_copilot.audit")
DEFAULT_MAX_TICKET_CHARACTERS = 8_000


class DraftRequest(BaseModel):
    ticket: str = Field(min_length=1)
    limit: int = Field(default=3, ge=1, le=5)


class CitationResponse(BaseModel):
    document_id: str
    title: str
    source: str
    passage: str
    score: float


class DraftResponseBody(BaseModel):
    request_id: str
    answer: str
    citations: list[CitationResponse]
    needs_human_review: bool
    review_reasons: list[str]
    evidence_decision: str
    scope_route: str
    trajectory: list[str]


def load_knowledge(path: Path) -> KnowledgeBase:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return KnowledgeBase([KnowledgeDocument(**item) for item in payload])


def load_api_keys(raw: str) -> dict[str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("SUPPORT_COPILOT_API_KEYS must be valid JSON") from error
    if not isinstance(payload, dict) or not payload:
        raise ValueError("SUPPORT_COPILOT_API_KEYS must map API keys to tenant IDs")
    if not all(
        isinstance(key, str) and key and isinstance(tenant, str) and tenant
        for key, tenant in payload.items()
    ):
        raise ValueError("API keys and tenant IDs must be non-empty strings")
    return payload


def load_api_key_hashes(raw: str) -> dict[str, str]:
    """Load a mapping of SHA-256 API-key digests to tenant IDs."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("API key hash secret must be valid JSON") from error
    if not isinstance(payload, dict) or not payload:
        raise ValueError("API key hash secret must map digests to tenant IDs")
    normalized: dict[str, str] = {}
    for digest, tenant in payload.items():
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
            or not isinstance(tenant, str)
            or not tenant
        ):
            raise ValueError(
                "API key hashes must be 64 hexadecimal characters and tenant IDs "
                "must be non-empty strings"
            )
        normalized[digest.lower()] = tenant
    return normalized


def create_app(
    knowledge_base: KnowledgeBase,
    api_keys: Mapping[str, str],
    max_ticket_characters: int = DEFAULT_MAX_TICKET_CHARACTERS,
    evidence_verifier: EvidenceVerifier | None = None,
    minimum_score: float = DEFAULT_MINIMUM_SCORE,
    minimum_score_ratio: float = DEFAULT_MINIMUM_SCORE_RATIO,
    api_keys_are_sha256: bool = False,
) -> FastAPI:
    if not api_keys:
        raise ValueError("at least one API key is required")
    unknown_tenants = set(api_keys.values()) - knowledge_base.tenant_ids
    if unknown_tenants:
        raise ValueError(f"API keys reference unknown tenants: {sorted(unknown_tenants)}")
    if max_ticket_characters <= 0:
        raise ValueError("max_ticket_characters must be positive")
    if minimum_score < 0 or minimum_score_ratio <= 0:
        raise ValueError("retrieval confidence thresholds must be positive")
    key_hashes = (
        load_api_key_hashes(json.dumps(dict(api_keys)))
        if api_keys_are_sha256
        else {
            hashlib.sha256(key.encode("utf-8")).hexdigest(): tenant
            for key, tenant in api_keys.items()
        }
    )

    app = FastAPI(
        title="Evidence-Gated Support Copilot",
        description="Kubernetes-core reference implementation",
        version="0.1.0",
    )
    configured_verifier = evidence_verifier or FailClosedEvidenceVerifier()
    verifier_mode = getattr(
        configured_verifier,
        "provider_name",
        "configured",
    )

    def authenticate(authorization: str | None = Header(default=None)) -> str:
        scheme, separator, token = (authorization or "").partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        authenticated_tenant: str | None = None
        for candidate_digest, tenant_id in key_hashes.items():
            if hmac.compare_digest(token_digest, candidate_digest):
                authenticated_tenant = tenant_id
        if authenticated_tenant is not None:
            return authenticated_tenant
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def demo() -> str:
        return DEMO_HTML

    @app.get("/readyz")
    def ready() -> dict[str, object]:
        return {
            "status": "ready",
            "tenant_count": len(knowledge_base.tenant_ids),
            "evidence_verifier": verifier_mode,
            "minimum_score": minimum_score,
            "minimum_score_ratio": minimum_score_ratio,
        }

    @app.post("/v1/drafts", response_model=DraftResponseBody)
    def draft(
        payload: DraftRequest,
        tenant_id: str = Depends(authenticate),
        x_request_id: str | None = Header(default=None),
    ) -> DraftResponseBody:
        ticket = payload.ticket.strip()
        if not ticket:
            raise HTTPException(status_code=422, detail="ticket cannot be blank")
        if len(ticket) > max_ticket_characters:
            raise HTTPException(status_code=413, detail="ticket is too large")
        request_id = (
            x_request_id
            if x_request_id and len(x_request_id) <= 128
            else str(uuid.uuid4())
        )
        started = time.monotonic()
        response = SupportCopilot(
            knowledge_base,
            tenant_id=tenant_id,
            evidence_verifier=configured_verifier,
            minimum_score=minimum_score,
            minimum_score_ratio=minimum_score_ratio,
        ).draft(ticket, limit=payload.limit)
        LOGGER.info(
            json.dumps(
                {
                    "event": "draft_completed",
                    "request_id": request_id,
                    "tenant_id": tenant_id,
                    "citation_ids": [item.document_id for item in response.citations],
                    "needs_human_review": response.needs_human_review,
                    "review_reasons": list(response.review_reasons),
                    "evidence_decision": response.evidence_decision,
                    "scope_route": response.scope_route,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
                separators=(",", ":"),
            )
        )
        return DraftResponseBody(
            request_id=request_id,
            answer=response.answer,
            citations=[
                CitationResponse(
                    document_id=item.document_id,
                    title=item.title,
                    source=item.source,
                    passage=item.passage,
                    score=item.score,
                )
                for item in response.citations
            ],
            needs_human_review=response.needs_human_review,
            review_reasons=list(response.review_reasons),
            evidence_decision=response.evidence_decision,
            scope_route=response.scope_route,
            trajectory=list(response.trajectory),
        )

    return app


def create_app_from_env() -> FastAPI:
    knowledge_path = os.environ.get("SUPPORT_COPILOT_KNOWLEDGE_PATH")
    raw_api_keys = os.environ.get("SUPPORT_COPILOT_API_KEYS")
    api_key_hashes_path = os.environ.get("SUPPORT_COPILOT_API_KEY_HASHES_FILE")
    if raw_api_keys and api_key_hashes_path:
        raise RuntimeError(
            "configure only one of SUPPORT_COPILOT_API_KEYS or "
            "SUPPORT_COPILOT_API_KEY_HASHES_FILE"
        )
    if not knowledge_path or not (raw_api_keys or api_key_hashes_path):
        raise RuntimeError(
            "SUPPORT_COPILOT_KNOWLEDGE_PATH and one API-key source are required"
        )
    if api_key_hashes_path:
        key_mapping = load_api_key_hashes(
            Path(api_key_hashes_path).read_text(encoding="utf-8")
        )
        api_keys_are_sha256 = True
    else:
        assert raw_api_keys is not None
        key_mapping = load_api_keys(raw_api_keys)
        api_keys_are_sha256 = False
    maximum = int(
        os.environ.get(
            "SUPPORT_COPILOT_MAX_TICKET_CHARACTERS",
            str(DEFAULT_MAX_TICKET_CHARACTERS),
        )
    )
    minimum_score = float(
        os.environ.get("SUPPORT_COPILOT_MINIMUM_SCORE", str(DEFAULT_MINIMUM_SCORE))
    )
    minimum_score_ratio = float(
        os.environ.get(
            "SUPPORT_COPILOT_MINIMUM_SCORE_RATIO",
            str(DEFAULT_MINIMUM_SCORE_RATIO),
        )
    )
    verifier_name = os.environ.get(
        "SUPPORT_COPILOT_EVIDENCE_VERIFIER",
        "fail_closed",
    )
    if verifier_name == "fail_closed":
        evidence_verifier = FailClosedEvidenceVerifier()
    elif verifier_name == "local_demo":
        evidence_verifier = LocalOverlapEvidenceVerifier()
    elif verifier_name == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI verifier")
        model = os.environ.get("SUPPORT_COPILOT_OPENAI_MODEL")
        if not model:
            raise RuntimeError(
                "SUPPORT_COPILOT_OPENAI_MODEL is required for the OpenAI verifier"
            )
        evidence_verifier = OpenAIEvidenceVerifier(model=model)
    elif verifier_name == "groq":
        if not os.environ.get("GROQ_API_KEY"):
            raise RuntimeError("GROQ_API_KEY is required for the Groq verifier")
        model = os.environ.get(
            "SUPPORT_COPILOT_GROQ_MODEL",
            DEFAULT_GROQ_MODEL,
        )
        evidence_verifier = GroqEvidenceVerifier(model=model)
    else:
        raise RuntimeError(
            "SUPPORT_COPILOT_EVIDENCE_VERIFIER must be fail_closed, local_demo, openai, or groq"
        )
    return create_app(
        load_knowledge(Path(knowledge_path)),
        key_mapping,
        max_ticket_characters=maximum,
        evidence_verifier=evidence_verifier,
        minimum_score=minimum_score,
        minimum_score_ratio=minimum_score_ratio,
        api_keys_are_sha256=api_keys_are_sha256,
    )
