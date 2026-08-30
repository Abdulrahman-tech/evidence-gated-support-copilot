"""Review-only storage and verification for GitHub issue webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

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


class ReviewQueue(Protocol):
    storage_name: str

    def healthcheck(self) -> None: ...

    def begin_delivery(self, delivery_id: str) -> tuple[ReviewRecord | None, bool]: ...

    def release_delivery(self, delivery_id: str) -> None: ...

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
    ) -> tuple[ReviewRecord, bool]: ...

    def list_for_tenant(self, tenant_id: str) -> tuple[ReviewRecord, ...]: ...

    def get_for_tenant(self, review_id: str, tenant_id: str) -> ReviewRecord | None: ...

    def decide(
        self,
        review_id: str,
        tenant_id: str,
        action: str,
        edited_answer: str | None,
    ) -> ReviewRecord: ...


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


def _record(row: Mapping[str, Any]) -> ReviewRecord:
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


class SQLiteReviewQueue:
    """Transactional review queue with durable delivery idempotency."""

    SCHEMA_VERSION = 1
    storage_name = "sqlite"

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

    def begin_delivery(self, delivery_id: str) -> tuple[ReviewRecord | None, bool]:
        """Atomically claim a delivery before any verifier work begins."""

        now = int(self.clock())
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM reviews WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            if row is not None:
                return _record(dict(row)), False
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

    def healthcheck(self) -> None:
        with self._read() as connection:
            if connection.execute("SELECT 1").fetchone()[0] != 1:
                raise RuntimeError("review database health check failed")

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
                return _record(dict(existing)), False
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
                    _draft_json(record.draft),
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
        return tuple(_record(dict(row)) for row in rows)

    def get_for_tenant(self, review_id: str, tenant_id: str) -> ReviewRecord | None:
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM reviews WHERE review_id = ? AND tenant_id = ?",
                (review_id, tenant_id),
            ).fetchone()
        return _record(dict(row)) if row is not None else None

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
            record = _record(dict(row))
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
            return _record(dict(updated_row))


class PostgreSQLReviewQueue:
    """Transactional hosted review queue using standard PostgreSQL."""

    SCHEMA_VERSION = 1
    storage_name = "postgresql"
    _MIGRATION_LOCK_ID = 875_315_001

    def __init__(
        self,
        dsn: str,
        *,
        claim_ttl_seconds: int = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be positive")
        if not dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("review database URL must use PostgreSQL")
        parsed_dsn = urlsplit(dsn)
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        ssl_mode = parse_qs(parsed_dsn.query).get("sslmode", [""])[0]
        if parsed_dsn.hostname not in local_hosts and ssl_mode not in {
            "require",
            "verify-ca",
            "verify-full",
        }:
            raise ValueError("remote review database URL must require TLS")
        self.dsn = dsn
        self.claim_ttl_seconds = claim_ttl_seconds
        self.clock = clock
        self._migrate()

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError("PostgreSQL review storage requires psycopg") from error
        return psycopg.connect(
            self.dsn,
            application_name="support-copilot-review",
            connect_timeout=5,
            prepare_threshold=None,
            row_factory=dict_row,
        )

    @contextmanager
    def _write(self):
        connection = self._connect()
        try:
            connection.execute("SET LOCAL statement_timeout = '5000ms'")
            connection.execute("SET LOCAL lock_timeout = '5000ms'")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _read(self):
        connection = self._connect()
        try:
            connection.execute("SET LOCAL statement_timeout = '5000ms'")
            yield connection
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._write() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (self._MIGRATION_LOCK_ID,),
            )
            connection.execute("CREATE SCHEMA IF NOT EXISTS support_copilot")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS support_copilot.schema_versions (
                    component TEXT PRIMARY KEY,
                    version INTEGER NOT NULL CHECK (version >= 0)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO support_copilot.schema_versions (component, version)
                VALUES ('github_review', 0)
                ON CONFLICT (component) DO NOTHING
                """
            )
            version = connection.execute(
                """
                SELECT version FROM support_copilot.schema_versions
                WHERE component = 'github_review'
                FOR UPDATE
                """
            ).fetchone()["version"]
            if version > self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"review database schema {version} is newer than supported "
                    f"version {self.SCHEMA_VERSION}"
                )
            if version == 0:
                connection.execute(
                    """
                    CREATE TABLE support_copilot.reviews (
                        sequence_id BIGSERIAL UNIQUE,
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
                    ON support_copilot.reviews (tenant_id)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE support_copilot.delivery_claims (
                        delivery_id TEXT PRIMARY KEY,
                        claimed_at BIGINT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    UPDATE support_copilot.schema_versions SET version = 1
                    WHERE component = 'github_review'
                    """
                )
            tables = {
                row["table_name"]
                for row in connection.execute(
                    """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'support_copilot'
                    """
                ).fetchall()
            }
            if not {"reviews", "delivery_claims", "schema_versions"}.issubset(tables):
                raise RuntimeError("review database schema is incomplete")
            review_columns = {
                row["column_name"]
                for row in connection.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'support_copilot'
                        AND table_name = 'reviews'
                    """
                ).fetchall()
            }
            required_review_columns = {
                "sequence_id",
                "review_id",
                "delivery_id",
                "tenant_id",
                "repository",
                "issue_number",
                "issue_url",
                "ticket",
                "draft_json",
                "status",
                "final_answer",
            }
            if not required_review_columns.issubset(review_columns):
                raise RuntimeError("review database schema is incomplete")

    def begin_delivery(self, delivery_id: str) -> tuple[ReviewRecord | None, bool]:
        now = int(self.clock())
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM support_copilot.reviews WHERE delivery_id = %s",
                (delivery_id,),
            ).fetchone()
            if row is not None:
                return _record(row), False
            connection.execute(
                """
                DELETE FROM support_copilot.delivery_claims
                WHERE delivery_id = %s AND claimed_at <= %s
                """,
                (delivery_id, now - self.claim_ttl_seconds),
            )
            claimed = connection.execute(
                """
                INSERT INTO support_copilot.delivery_claims (delivery_id, claimed_at)
                VALUES (%s, %s)
                ON CONFLICT (delivery_id) DO NOTHING
                RETURNING delivery_id
                """,
                (delivery_id, now),
            ).fetchone()
            return None, claimed is not None

    def healthcheck(self) -> None:
        with self._read() as connection:
            result = connection.execute("SELECT 1 AS healthy").fetchone()
            if result["healthy"] != 1:
                raise RuntimeError("review database health check failed")

    def release_delivery(self, delivery_id: str) -> None:
        with self._write() as connection:
            connection.execute(
                "DELETE FROM support_copilot.delivery_claims WHERE delivery_id = %s",
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
        with self._write() as connection:
            inserted = connection.execute(
                """
                INSERT INTO support_copilot.reviews (
                    review_id, delivery_id, tenant_id, repository, issue_number,
                    issue_url, ticket, draft_json, status, final_answer
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (delivery_id) DO NOTHING
                RETURNING *
                """,
                (
                    record.review_id,
                    record.delivery_id,
                    record.tenant_id,
                    record.repository,
                    record.issue_number,
                    record.issue_url,
                    record.ticket,
                    _draft_json(record.draft),
                    record.status,
                    record.final_answer,
                ),
            ).fetchone()
            connection.execute(
                "DELETE FROM support_copilot.delivery_claims WHERE delivery_id = %s",
                (delivery_id,),
            )
            if inserted is not None:
                return _record(inserted), True
            existing = connection.execute(
                "SELECT * FROM support_copilot.reviews WHERE delivery_id = %s",
                (delivery_id,),
            ).fetchone()
            return _record(existing), False

    def list_for_tenant(self, tenant_id: str) -> tuple[ReviewRecord, ...]:
        with self._read() as connection:
            rows = connection.execute(
                """
                SELECT * FROM support_copilot.reviews
                WHERE tenant_id = %s ORDER BY sequence_id
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(_record(row) for row in rows)

    def get_for_tenant(self, review_id: str, tenant_id: str) -> ReviewRecord | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT * FROM support_copilot.reviews
                WHERE review_id = %s AND tenant_id = %s
                """,
                (review_id, tenant_id),
            ).fetchone()
        return _record(row) if row is not None else None

    def decide(
        self,
        review_id: str,
        tenant_id: str,
        action: str,
        edited_answer: str | None,
    ) -> ReviewRecord:
        with self._write() as connection:
            row = connection.execute(
                """
                SELECT * FROM support_copilot.reviews
                WHERE review_id = %s AND tenant_id = %s
                FOR UPDATE
                """,
                (review_id, tenant_id),
            ).fetchone()
            if row is None:
                raise KeyError(review_id)
            record = _record(row)
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
            updated = connection.execute(
                """
                UPDATE support_copilot.reviews
                SET status = %s, final_answer = %s
                WHERE review_id = %s
                RETURNING *
                """,
                (status, final_answer, review_id),
            ).fetchone()
            return _record(updated)
