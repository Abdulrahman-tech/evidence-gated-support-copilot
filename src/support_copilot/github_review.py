"""Review-only storage and verification for GitHub issue webhooks."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass, replace
from threading import Lock

from support_copilot.models import DraftResponse


MAX_WEBHOOK_BYTES = 256_000


def verify_webhook_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    supplied = signature.removeprefix("sha256=")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return len(supplied) == len(expected) and hmac.compare_digest(supplied, expected)


@dataclass(frozen=True)
class ReviewRecord:
    review_id: str
    delivery_id: str
    tenant_id: str
    repository: str
    issue_number: int
    issue_url: str
    ticket: str
    draft: DraftResponse
    status: str = "pending"
    final_answer: str | None = None


class ReviewQueue:
    """Thread-safe process-local queue with GitHub-delivery idempotency."""

    def __init__(self) -> None:
        self._records: dict[str, ReviewRecord] = {}
        self._delivery_ids: dict[str, str] = {}
        self._processing: set[str] = set()
        self._lock = Lock()

    def begin_delivery(self, delivery_id: str) -> tuple[ReviewRecord | None, bool]:
        """Atomically claim a delivery before any verifier work begins."""

        with self._lock:
            review_id = self._delivery_ids.get(delivery_id)
            if review_id is not None:
                return self._records[review_id], False
            if delivery_id in self._processing:
                return None, False
            self._processing.add(delivery_id)
            return None, True

    def release_delivery(self, delivery_id: str) -> None:
        with self._lock:
            self._processing.discard(delivery_id)

    def enqueue(
        self,
        *,
        delivery_id: str,
        tenant_id: str,
        repository: str,
        issue_number: int,
        issue_url: str,
        ticket: str,
        draft: DraftResponse,
    ) -> tuple[ReviewRecord, bool]:
        with self._lock:
            existing_id = self._delivery_ids.get(delivery_id)
            if existing_id is not None:
                return self._records[existing_id], False
            record = ReviewRecord(
                review_id=str(uuid.uuid4()),
                delivery_id=delivery_id,
                tenant_id=tenant_id,
                repository=repository,
                issue_number=issue_number,
                issue_url=issue_url,
                ticket=ticket,
                draft=draft,
            )
            self._records[record.review_id] = record
            self._delivery_ids[delivery_id] = record.review_id
            self._processing.discard(delivery_id)
            return record, True

    def list_for_tenant(self, tenant_id: str) -> tuple[ReviewRecord, ...]:
        with self._lock:
            return tuple(
                record
                for record in self._records.values()
                if record.tenant_id == tenant_id
            )

    def get_for_tenant(self, review_id: str, tenant_id: str) -> ReviewRecord | None:
        with self._lock:
            record = self._records.get(review_id)
            if record is None or record.tenant_id != tenant_id:
                return None
            return record

    def decide(
        self,
        review_id: str,
        tenant_id: str,
        action: str,
        edited_answer: str | None,
    ) -> ReviewRecord:
        with self._lock:
            record = self._records.get(review_id)
            if record is None or record.tenant_id != tenant_id:
                raise KeyError(review_id)
            if record.status != "pending":
                raise ValueError("review has already been decided")
            if action == "approve":
                final_answer = (
                    record.draft.answer if edited_answer is None else edited_answer
                ).strip()
                if not final_answer:
                    raise ValueError("approved answer cannot be blank")
                status = "approved"
            elif action == "reject":
                if edited_answer is not None:
                    raise ValueError("rejected reviews cannot include an edited answer")
                final_answer = None
                status = "rejected"
            else:
                raise ValueError("action must be approve or reject")
            updated = replace(record, status=status, final_answer=final_answer)
            self._records[review_id] = updated
            return updated
