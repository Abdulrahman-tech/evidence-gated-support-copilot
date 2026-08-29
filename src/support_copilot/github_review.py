"""Review-only storage and verification for GitHub issue webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from support_copilot.models import DraftResponse, SearchResult


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


class SQLiteReviewQueue:
    """Transactional review queue with durable delivery idempotency."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: Path,
        *,
        claim_ttl_seconds: int = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be positive")
        self.path = path.expanduser().resolve()
        self.claim_ttl_seconds = claim_ttl_seconds
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_RDWR,
                0o600,
            )
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        self._secure_files()
        connection = self._connect()
        try:
            journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if journal_mode.lower() != "wal":
                raise RuntimeError("review database could not enable WAL mode")
        finally:
            connection.close()
        self._migrate()
        self._secure_files()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _secure_files(self) -> None:
        for path in (
            self.path,
            Path(f"{self.path}-wal"),
            Path(f"{self.path}-shm"),
        ):
            if path.exists():
                os.chmod(path, 0o600)

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._secure_files()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._write() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"review database schema {version} is newer than supported "
                    f"version {self.SCHEMA_VERSION}"
                )
            if version == 0:
                connection.execute(
                    """
                    CREATE TABLE reviews (
                        review_id TEXT PRIMARY KEY,
                        delivery_id TEXT NOT NULL UNIQUE,
                        tenant_id TEXT NOT NULL,
                        repository TEXT NOT NULL,
                        issue_number INTEGER NOT NULL CHECK (issue_number > 0),
                        issue_url TEXT NOT NULL,
                        ticket TEXT NOT NULL,
                        draft_json TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'approved', 'rejected')),
                        final_answer TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX reviews_tenant_id_index
                        ON reviews (tenant_id)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE delivery_claims (
                        delivery_id TEXT PRIMARY KEY,
                        claimed_at INTEGER NOT NULL
                    )
                    """
                )
                connection.execute("PRAGMA user_version = 1")
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError("review database integrity check failed")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if not {"reviews", "delivery_claims"}.issubset(tables):
                raise RuntimeError("review database schema is incomplete")

    @staticmethod
    def _draft_json(draft: DraftResponse) -> str:
        return json.dumps(
            {
                "answer": draft.answer,
                "citations": [asdict(citation) for citation in draft.citations],
                "needs_human_review": draft.needs_human_review,
                "review_reasons": list(draft.review_reasons),
                "evidence_decision": draft.evidence_decision,
                "scope_route": draft.scope_route,
                "trajectory": list(draft.trajectory),
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> ReviewRecord:
        try:
            payload = json.loads(row["draft_json"])
            draft = DraftResponse(
                answer=payload["answer"],
                citations=tuple(
                    SearchResult(**citation) for citation in payload["citations"]
                ),
                needs_human_review=payload["needs_human_review"],
                review_reasons=tuple(payload["review_reasons"]),
                evidence_decision=payload["evidence_decision"],
                scope_route=payload["scope_route"],
                trajectory=tuple(payload["trajectory"]),
            )
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("stored review draft is invalid") from error
        return ReviewRecord(
            review_id=row["review_id"],
            delivery_id=row["delivery_id"],
            tenant_id=row["tenant_id"],
            repository=row["repository"],
            issue_number=row["issue_number"],
            issue_url=row["issue_url"],
            ticket=row["ticket"],
            draft=draft,
            status=row["status"],
            final_answer=row["final_answer"],
        )

    def begin_delivery(self, delivery_id: str) -> tuple[ReviewRecord | None, bool]:
        """Atomically claim a delivery before any verifier work begins."""

        now = int(self.clock())
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM reviews WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            if row is not None:
                return self._record(row), False
            connection.execute(
                "DELETE FROM delivery_claims WHERE delivery_id = ? AND claimed_at <= ?",
                (delivery_id, now - self.claim_ttl_seconds),
            )
            try:
                connection.execute(
                    "INSERT INTO delivery_claims (delivery_id, claimed_at) VALUES (?, ?)",
                    (delivery_id, now),
                )
            except sqlite3.IntegrityError:
                return None, False
            return None, True

    def release_delivery(self, delivery_id: str) -> None:
        with self._write() as connection:
            connection.execute(
                "DELETE FROM delivery_claims WHERE delivery_id = ?",
                (delivery_id,),
            )

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
        with self._write() as connection:
            existing = connection.execute(
                "SELECT * FROM reviews WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            if existing is not None:
                return self._record(existing), False
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
            connection.execute(
                """
                INSERT INTO reviews (
                    review_id, delivery_id, tenant_id, repository, issue_number,
                    issue_url, ticket, draft_json, status, final_answer
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.review_id,
                    record.delivery_id,
                    record.tenant_id,
                    record.repository,
                    record.issue_number,
                    record.issue_url,
                    record.ticket,
                    self._draft_json(record.draft),
                    record.status,
                    record.final_answer,
                ),
            )
            connection.execute(
                "DELETE FROM delivery_claims WHERE delivery_id = ?",
                (delivery_id,),
            )
            return record, True

    def list_for_tenant(self, tenant_id: str) -> tuple[ReviewRecord, ...]:
        with self._read() as connection:
            rows = connection.execute(
                "SELECT * FROM reviews WHERE tenant_id = ? ORDER BY rowid",
                (tenant_id,),
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    def get_for_tenant(self, review_id: str, tenant_id: str) -> ReviewRecord | None:
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM reviews WHERE review_id = ? AND tenant_id = ?",
                (review_id, tenant_id),
            ).fetchone()
        return self._record(row) if row is not None else None

    def decide(
        self,
        review_id: str,
        tenant_id: str,
        action: str,
        edited_answer: str | None,
    ) -> ReviewRecord:
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM reviews WHERE review_id = ? AND tenant_id = ?",
                (review_id, tenant_id),
            ).fetchone()
            if row is None:
                raise KeyError(review_id)
            record = self._record(row)
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
            connection.execute(
                "UPDATE reviews SET status = ?, final_answer = ? WHERE review_id = ?",
                (status, final_answer, review_id),
            )
            updated_row = connection.execute(
                "SELECT * FROM reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
            return self._record(updated_row)
