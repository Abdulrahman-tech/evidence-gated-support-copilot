"""Authenticated HTTP boundary for the support copilot."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import re
import time
import uuid
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import Lock

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from support_copilot.copilot import SupportCopilot
from support_copilot.evidence import EvidenceVerifier, FailClosedEvidenceVerifier
from support_copilot.evidence import LocalOverlapEvidenceVerifier
from support_copilot.demo import DEMO_HTML
from support_copilot.groq_evidence import DEFAULT_GROQ_MODEL, GroqEvidenceVerifier
from support_copilot.github_review import (
    MAX_WEBHOOK_BYTES,
    PostgreSQLReviewQueue,
    ReviewRecord,
    SQLiteReviewQueue,
    verify_webhook_signature,
)
from support_copilot.knowledge import (
    DEFAULT_MINIMUM_SCORE,
    DEFAULT_MINIMUM_SCORE_RATIO,
    KnowledgeBase,
)
from support_copilot.models import KnowledgeDocument
from support_copilot.openai_evidence import OpenAIEvidenceVerifier


LOGGER = logging.getLogger("support_copilot.audit")
DEFAULT_MAX_TICKET_CHARACTERS = 8_000
DEFAULT_RATE_LIMIT_REQUESTS = 60
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "testserver")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; connect-src 'self'; "
        "form-action 'none'; frame-ancestors 'none'; img-src 'self' data:; "
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
    ),
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


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


class ReviewDecisionRequest(BaseModel):
    action: str
    edited_answer: str | None = Field(default=None, max_length=16_000)


class ReviewResponseBody(BaseModel):
    review_id: str
    delivery_id: str
    repository: str
    issue_number: int
    issue_url: str
    ticket: str
    status: str
    answer: str
    final_answer: str | None
    citations: list[CitationResponse]
    needs_human_review: bool
    review_reasons: list[str]
    evidence_decision: str
    scope_route: str
    trajectory: list[str]
    posting_status: str = "disabled"


def safe_request_id(value: str | None) -> str:
    if value and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid.uuid4())


def configure_audit_logging() -> None:
    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


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


def load_github_repositories(raw: str) -> dict[str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(
            "SUPPORT_COPILOT_GITHUB_REPOSITORIES must be valid JSON"
        ) from error
    if not isinstance(payload, dict) or not payload or not all(
        isinstance(repository, str)
        and repository
        and isinstance(tenant, str)
        and tenant
        for repository, tenant in payload.items()
    ):
        raise ValueError(
            "SUPPORT_COPILOT_GITHUB_REPOSITORIES must map repositories to tenants"
        )
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
    rate_limit_requests: int = DEFAULT_RATE_LIMIT_REQUESTS,
    rate_limit_window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    allowed_hosts: Sequence[str] = DEFAULT_ALLOWED_HOSTS,
    release_id: str = "local",
    github_webhook_secret: str | None = None,
    github_repositories: Mapping[str, str] | None = None,
    github_review_database: Path | None = None,
    github_review_database_url: str | None = None,
    review_api_keys: Mapping[str, str] | None = None,
    review_api_keys_are_sha256: bool = False,
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
    if rate_limit_requests <= 0 or rate_limit_window_seconds <= 0:
        raise ValueError("rate limit values must be positive")
    if not allowed_hosts or any(not host.strip() for host in allowed_hosts):
        raise ValueError("allowed_hosts must contain non-empty host names")
    if not REQUEST_ID_PATTERN.fullmatch(release_id):
        raise ValueError("release_id must be a safe identifier of at most 128 characters")
    raw_repository_tenants = dict(github_repositories or {})
    if any(
        not isinstance(repository, str)
        or not repository
        or "/" not in repository
        or not isinstance(tenant, str)
        or not tenant
        for repository, tenant in raw_repository_tenants.items()
    ):
        raise ValueError("github_repositories must map owner/repository names to tenants")
    repository_tenants = {
        repository.lower(): tenant
        for repository, tenant in raw_repository_tenants.items()
    }
    configured_review_stores = sum(
        (github_review_database is not None, bool(github_review_database_url))
    )
    if configured_review_stores > 1:
        raise ValueError("configure only one GitHub review database")
    github_configuration = (
        bool(github_webhook_secret),
        bool(repository_tenants),
        configured_review_stores == 1,
    )
    if len(set(github_configuration)) != 1:
        raise ValueError(
            "github_webhook_secret, github_repositories, and one GitHub review "
            "database must be configured together"
        )
    raw_review_api_keys = dict(review_api_keys or {})
    if all(github_configuration) and not raw_review_api_keys:
        raise ValueError("GitHub integration requires separate review API keys")
    if raw_review_api_keys and not all(github_configuration):
        raise ValueError("review API keys require GitHub integration")
    if github_webhook_secret is not None and len(github_webhook_secret) < 16:
        raise ValueError("github_webhook_secret must contain at least 16 characters")
    unknown_repository_tenants = set(repository_tenants.values()) - knowledge_base.tenant_ids
    if unknown_repository_tenants:
        raise ValueError(
            "github_repositories reference unknown tenants: "
            f"{sorted(unknown_repository_tenants)}"
        )
    unknown_review_tenants = set(raw_review_api_keys.values()) - knowledge_base.tenant_ids
    if unknown_review_tenants:
        raise ValueError(
            f"review API keys reference unknown tenants: {sorted(unknown_review_tenants)}"
        )
    missing_review_tenants = set(repository_tenants.values()) - set(
        raw_review_api_keys.values()
    )
    if missing_review_tenants:
        raise ValueError(
            "review API keys do not cover repository tenants: "
            f"{sorted(missing_review_tenants)}"
        )
    key_hashes = (
        load_api_key_hashes(json.dumps(dict(api_keys)))
        if api_keys_are_sha256
        else {
            hashlib.sha256(key.encode("utf-8")).hexdigest(): tenant
            for key, tenant in api_keys.items()
        }
    )
    review_key_hashes = (
        load_api_key_hashes(json.dumps(raw_review_api_keys))
        if review_api_keys_are_sha256
        else {
            hashlib.sha256(key.encode("utf-8")).hexdigest(): tenant
            for key, tenant in raw_review_api_keys.items()
        }
    )
    if set(key_hashes) & set(review_key_hashes):
        raise ValueError("draft and review API keys must be different")

    app = FastAPI(
        title="Evidence-Gated Support Copilot",
        description="Kubernetes-core reference implementation",
        version="0.1.0",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
    configured_verifier = evidence_verifier or FailClosedEvidenceVerifier()
    verifier_mode = getattr(
        configured_verifier,
        "provider_name",
        "configured",
    )
    request_buckets: dict[str, deque[float]] = defaultdict(deque)
    rate_limit_lock = Lock()
    metrics: Counter[str] = Counter()
    metrics_lock = Lock()
    if github_review_database_url:
        review_queue = PostgreSQLReviewQueue(github_review_database_url)
    elif github_review_database is not None:
        review_queue = SQLiteReviewQueue(github_review_database)
    else:
        review_queue = None
    app.state.review_queue = review_queue

    @app.middleware("http")
    async def observe_and_secure(request: Request, call_next):
        started = time.monotonic()
        response_status = 500
        request_id = safe_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        try:
            response = await call_next(request)
            response_status = response.status_code
            return response
        finally:
            elapsed = time.monotonic() - started
            with metrics_lock:
                metrics["http_requests_total"] += 1
                metrics["http_request_duration_microseconds"] += round(
                    elapsed * 1_000_000
                )
                if response_status >= 400:
                    metrics["http_errors_total"] += 1
            if "response" in locals():
                response.headers["X-Request-ID"] = request_id
                for name, value in SECURITY_HEADERS.items():
                    response.headers[name] = value
            LOGGER.info(
                json.dumps(
                    {
                        "event": "http_request_completed",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response_status,
                        "duration_ms": round(elapsed * 1000, 2),
                    },
                    separators=(",", ":"),
                )
            )

    def increment_metric(name: str) -> None:
        with metrics_lock:
            metrics[name] += 1

    def review_body(record: ReviewRecord) -> ReviewResponseBody:
        return ReviewResponseBody(
            review_id=record.review_id,
            delivery_id=record.delivery_id,
            repository=record.repository,
            issue_number=record.issue_number,
            issue_url=record.issue_url,
            ticket=record.ticket,
            status=record.status,
            answer=record.draft.answer,
            final_answer=record.final_answer,
            citations=[
                CitationResponse(
                    document_id=item.document_id,
                    title=item.title,
                    source=item.source,
                    passage=item.passage,
                    score=item.score,
                )
                for item in record.draft.citations
            ],
            needs_human_review=record.draft.needs_human_review,
            review_reasons=list(record.draft.review_reasons),
            evidence_decision=record.draft.evidence_decision,
            scope_route=record.draft.scope_route,
            trajectory=list(record.draft.trajectory),
        )

    def enforce_rate_limit(token_digest: str) -> None:
        now = time.monotonic()
        cutoff = now - rate_limit_window_seconds
        with rate_limit_lock:
            bucket = request_buckets[token_digest]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= rate_limit_requests:
                increment_metric("rate_limited_total")
                retry_after = max(
                    1,
                    math.ceil(bucket[0] + rate_limit_window_seconds - now),
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)

    def authenticate_against(
        authorization: str | None,
        allowed_key_hashes: Mapping[str, str],
    ) -> str:
        scheme, separator, token = (authorization or "").partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        authenticated_tenant: str | None = None
        for candidate_digest, tenant_id in allowed_key_hashes.items():
            if hmac.compare_digest(token_digest, candidate_digest):
                authenticated_tenant = tenant_id
        if authenticated_tenant is not None:
            enforce_rate_limit(token_digest)
            return authenticated_tenant
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def authenticate(authorization: str | None = Header(default=None)) -> str:
        return authenticate_against(authorization, key_hashes)

    def authenticate_review(
        authorization: str | None = Header(default=None),
    ) -> str:
        return authenticate_against(authorization, review_key_hashes)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def demo() -> str:
        return DEMO_HTML

    @app.get("/readyz")
    def ready() -> dict[str, object]:
        if review_queue is not None:
            try:
                review_queue.healthcheck()
            except Exception as error:
                LOGGER.error(
                    json.dumps(
                        {
                            "event": "review_storage_unavailable",
                            "error_type": type(error).__name__,
                        },
                        separators=(",", ":"),
                    )
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="review storage unavailable",
                ) from error
        return {
            "status": "ready",
            "release": release_id,
            "tenant_count": len(knowledge_base.tenant_ids),
            "evidence_verifier": verifier_mode,
            "minimum_score": minimum_score,
            "minimum_score_ratio": minimum_score_ratio,
            "github_integration": "review_only" if review_queue else "disabled",
            "github_review_storage": (
                review_queue.storage_name if review_queue else "disabled"
            ),
            "github_posting": "disabled",
        }

    @app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
    def prometheus_metrics() -> str:
        with metrics_lock:
            snapshot = metrics.copy()
        duration_seconds = (
            snapshot["http_request_duration_microseconds"] / 1_000_000
        )
        return "\n".join(
            (
                "# HELP support_copilot_http_requests_total HTTP requests received.",
                "# TYPE support_copilot_http_requests_total counter",
                f"support_copilot_http_requests_total {snapshot['http_requests_total']}",
                "# HELP support_copilot_http_errors_total HTTP responses with status 4xx or 5xx.",
                "# TYPE support_copilot_http_errors_total counter",
                f"support_copilot_http_errors_total {snapshot['http_errors_total']}",
                "# HELP support_copilot_http_request_duration_seconds_sum Total request duration.",
                "# TYPE support_copilot_http_request_duration_seconds_sum counter",
                "support_copilot_http_request_duration_seconds_sum "
                f"{duration_seconds:.6f}",
                "# HELP support_copilot_drafts_supported_total Drafts returned with direct evidence.",
                "# TYPE support_copilot_drafts_supported_total counter",
                f"support_copilot_drafts_supported_total {snapshot['drafts_supported_total']}",
                "# HELP support_copilot_drafts_abstained_total Drafts that abstained or routed out.",
                "# TYPE support_copilot_drafts_abstained_total counter",
                f"support_copilot_drafts_abstained_total {snapshot['drafts_abstained_total']}",
                "# HELP support_copilot_draft_failures_total Unhandled draft-generation failures.",
                "# TYPE support_copilot_draft_failures_total counter",
                f"support_copilot_draft_failures_total {snapshot['draft_failures_total']}",
                "# HELP support_copilot_rate_limited_total Authenticated requests rejected by the application limiter.",
                "# TYPE support_copilot_rate_limited_total counter",
                f"support_copilot_rate_limited_total {snapshot['rate_limited_total']}",
                "# HELP support_copilot_github_webhooks_accepted_total Signed issue webhooks queued for review.",
                "# TYPE support_copilot_github_webhooks_accepted_total counter",
                "support_copilot_github_webhooks_accepted_total "
                f"{snapshot['github_webhooks_accepted_total']}",
                "# HELP support_copilot_github_webhook_duplicates_total Duplicate deliveries safely ignored.",
                "# TYPE support_copilot_github_webhook_duplicates_total counter",
                "support_copilot_github_webhook_duplicates_total "
                f"{snapshot['github_webhook_duplicates_total']}",
                "# HELP support_copilot_github_reviews_approved_total Reviews approved without posting.",
                "# TYPE support_copilot_github_reviews_approved_total counter",
                "support_copilot_github_reviews_approved_total "
                f"{snapshot['github_reviews_approved_total']}",
                "# HELP support_copilot_github_reviews_rejected_total Reviews rejected without posting.",
                "# TYPE support_copilot_github_reviews_rejected_total counter",
                "support_copilot_github_reviews_rejected_total "
                f"{snapshot['github_reviews_rejected_total']}",
                "",
            )
        )

    @app.post("/v1/github/webhooks", status_code=status.HTTP_202_ACCEPTED)
    async def github_webhook(request: Request) -> dict[str, object]:
        if review_queue is None or github_webhook_secret is None:
            raise HTTPException(status_code=503, detail="GitHub integration is disabled")
        body_buffer = bytearray()
        async for chunk in request.stream():
            if len(body_buffer) + len(chunk) > MAX_WEBHOOK_BYTES:
                raise HTTPException(status_code=413, detail="webhook payload is too large")
            body_buffer.extend(chunk)
        body = bytes(body_buffer)
        if not verify_webhook_signature(
            body,
            request.headers.get("X-Hub-Signature-256"),
            github_webhook_secret,
        ):
            raise HTTPException(status_code=401, detail="invalid webhook signature")
        delivery_id = request.headers.get("X-GitHub-Delivery")
        if not delivery_id or not REQUEST_ID_PATTERN.fullmatch(delivery_id):
            raise HTTPException(status_code=400, detail="invalid GitHub delivery ID")
        if request.headers.get("X-GitHub-Event") != "issues":
            return {"status": "ignored", "reason": "unsupported event"}
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=400, detail="invalid webhook JSON") from error
        if not isinstance(payload, dict) or payload.get("action") != "opened":
            return {"status": "ignored", "reason": "unsupported issue action"}
        repository = payload.get("repository")
        issue = payload.get("issue")
        repository_full_name = (
            repository.get("full_name", "") if isinstance(repository, dict) else ""
        )
        repository_name = (
            repository_full_name.lower()
            if isinstance(repository_full_name, str)
            else ""
        )
        tenant_id = repository_tenants.get(repository_name)
        if tenant_id is None:
            return {"status": "ignored", "reason": "repository is not configured"}
        if not isinstance(issue, dict):
            raise HTTPException(status_code=400, detail="webhook issue is missing")
        title = issue.get("title")
        issue_body = issue.get("body") or ""
        issue_number = issue.get("number")
        issue_url = issue.get("html_url")
        if (
            not isinstance(title, str)
            or not title.strip()
            or not isinstance(issue_body, str)
            or not isinstance(issue_number, int)
            or issue_number <= 0
            or not isinstance(issue_url, str)
            or issue_url
            != f"https://github.com/{repository_full_name}/issues/{issue_number}"
        ):
            raise HTTPException(status_code=400, detail="invalid webhook issue")
        ticket = f"{title.strip()}\n\n{issue_body.strip()}".strip()
        if len(ticket) > max_ticket_characters:
            raise HTTPException(status_code=413, detail="issue is too large")
        existing, claimed = review_queue.begin_delivery(delivery_id)
        if not claimed:
            increment_metric("github_webhook_duplicates_total")
            return {
                "status": "duplicate",
                "review_id": existing.review_id if existing is not None else None,
                "posting_status": "disabled",
            }
        try:
            draft_response = SupportCopilot(
                knowledge_base,
                tenant_id=tenant_id,
                evidence_verifier=configured_verifier,
                minimum_score=minimum_score,
                minimum_score_ratio=minimum_score_ratio,
            ).draft(ticket)
            record, _ = review_queue.enqueue(
                delivery_id=delivery_id,
                tenant_id=tenant_id,
                repository=repository_name,
                issue_number=issue_number,
                issue_url=issue_url,
                ticket=ticket,
                draft=draft_response,
            )
        except Exception:
            review_queue.release_delivery(delivery_id)
            increment_metric("draft_failures_total")
            raise
        increment_metric("github_webhooks_accepted_total")
        increment_metric(
            "drafts_supported_total"
            if draft_response.evidence_decision == "supported"
            else "drafts_abstained_total"
        )
        LOGGER.info(
            json.dumps(
                {
                    "event": "github_review_queued",
                    "request_id": request.state.request_id,
                    "review_id": record.review_id,
                    "repository": repository_name,
                    "issue_number": issue_number,
                    "evidence_decision": draft_response.evidence_decision,
                    "posting_status": "disabled",
                },
                separators=(",", ":"),
            )
        )
        return {
            "status": "queued",
            "review_id": record.review_id,
            "posting_status": "disabled",
        }

    @app.get("/v1/reviews", response_model=list[ReviewResponseBody])
    def list_reviews(
        tenant_id: str = Depends(authenticate_review),
    ) -> list[ReviewResponseBody]:
        if review_queue is None:
            raise HTTPException(status_code=503, detail="GitHub integration is disabled")
        return [review_body(item) for item in review_queue.list_for_tenant(tenant_id)]

    @app.patch("/v1/reviews/{review_id}", response_model=ReviewResponseBody)
    def decide_review(
        review_id: str,
        decision: ReviewDecisionRequest,
        request: Request,
        tenant_id: str = Depends(authenticate_review),
    ) -> ReviewResponseBody:
        if review_queue is None:
            raise HTTPException(status_code=503, detail="GitHub integration is disabled")
        try:
            record = review_queue.decide(
                review_id,
                tenant_id,
                decision.action,
                decision.edited_answer,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="review not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        increment_metric(f"github_reviews_{record.status}_total")
        LOGGER.info(
            json.dumps(
                {
                    "event": "github_review_decided",
                    "request_id": request.state.request_id,
                    "review_id": review_id,
                    "decision": record.status,
                    "posting_status": "disabled",
                },
                separators=(",", ":"),
            )
        )
        return review_body(record)

    @app.post("/v1/drafts", response_model=DraftResponseBody)
    def draft(
        payload: DraftRequest,
        request: Request,
        tenant_id: str = Depends(authenticate),
    ) -> DraftResponseBody:
        ticket = payload.ticket.strip()
        if not ticket:
            raise HTTPException(status_code=422, detail="ticket cannot be blank")
        if len(ticket) > max_ticket_characters:
            raise HTTPException(status_code=413, detail="ticket is too large")
        request_id = request.state.request_id
        started = time.monotonic()
        try:
            response = SupportCopilot(
                knowledge_base,
                tenant_id=tenant_id,
                evidence_verifier=configured_verifier,
                minimum_score=minimum_score,
                minimum_score_ratio=minimum_score_ratio,
            ).draft(ticket, limit=payload.limit)
        except Exception:
            increment_metric("draft_failures_total")
            raise
        if response.evidence_decision == "supported":
            increment_metric("drafts_supported_total")
        else:
            increment_metric("drafts_abstained_total")
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
    configure_audit_logging()
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
    rate_limit_requests = int(
        os.environ.get(
            "SUPPORT_COPILOT_RATE_LIMIT_REQUESTS",
            str(DEFAULT_RATE_LIMIT_REQUESTS),
        )
    )
    rate_limit_window_seconds = int(
        os.environ.get(
            "SUPPORT_COPILOT_RATE_LIMIT_WINDOW_SECONDS",
            str(DEFAULT_RATE_LIMIT_WINDOW_SECONDS),
        )
    )
    allowed_hosts = tuple(
        host.strip()
        for host in os.environ.get(
            "SUPPORT_COPILOT_ALLOWED_HOSTS",
            ",".join(DEFAULT_ALLOWED_HOSTS),
        ).split(",")
        if host.strip()
    )
    release_id = os.environ.get(
        "SUPPORT_COPILOT_RELEASE",
        os.environ.get("RENDER_GIT_COMMIT", "local"),
    )
    github_webhook_secret = os.environ.get("SUPPORT_COPILOT_GITHUB_WEBHOOK_SECRET")
    raw_github_repositories = os.environ.get(
        "SUPPORT_COPILOT_GITHUB_REPOSITORIES"
    )
    raw_review_api_key_hashes = os.environ.get(
        "SUPPORT_COPILOT_REVIEW_API_KEY_HASHES"
    )
    review_api_keys = (
        load_api_key_hashes(raw_review_api_key_hashes)
        if raw_review_api_key_hashes
        else None
    )
    github_repositories = (
        load_github_repositories(raw_github_repositories)
        if raw_github_repositories
        else None
    )
    github_review_database_value = os.environ.get(
        "SUPPORT_COPILOT_REVIEW_DB_PATH"
    )
    github_review_database = (
        Path(github_review_database_value)
        if github_review_database_value
        else None
    )
    github_review_database_url = os.environ.get(
        "SUPPORT_COPILOT_REVIEW_DATABASE_URL"
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
        rate_limit_requests=rate_limit_requests,
        rate_limit_window_seconds=rate_limit_window_seconds,
        allowed_hosts=allowed_hosts,
        release_id=release_id,
        github_webhook_secret=github_webhook_secret,
        github_repositories=github_repositories,
        github_review_database=github_review_database,
        github_review_database_url=github_review_database_url,
        review_api_keys=review_api_keys,
        review_api_keys_are_sha256=True,
    )
