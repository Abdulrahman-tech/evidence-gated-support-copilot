import os
import unittest
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from support_copilot.api import create_app
from support_copilot.github_review import PostgreSQLReviewQueue
from support_copilot.knowledge import KnowledgeBase
from support_copilot.models import DraftResponse, KnowledgeDocument, SearchResult


def sample_draft() -> DraftResponse:
    return DraftResponse(
        answer="Use a ClusterIP service for internal traffic.",
        citations=(
            SearchResult(
                document_id="kubernetes-service",
                title="Service",
                source="https://kubernetes.io/docs/concepts/services-networking/service/",
                passage="ClusterIP exposes the Service on a cluster-internal IP.",
                score=12.0,
                tenant_id="kubernetes",
            ),
        ),
        needs_human_review=True,
        review_reasons=("github_review_required",),
        evidence_decision="supported",
        scope_route="kubernetes_core",
        trajectory=("retrieved", "verified", "pending_review"),
    )


class PostgreSQLReviewQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dsn = os.environ.get("TEST_POSTGRES_DSN")
        if not cls.dsn:
            raise unittest.SkipTest("TEST_POSTGRES_DSN is not configured")
        import psycopg

        cls.psycopg = psycopg

    def setUp(self) -> None:
        with self.psycopg.connect(self.dsn) as connection:
            connection.execute("DROP SCHEMA IF EXISTS support_copilot CASCADE")

    def enqueue(self, queue: PostgreSQLReviewQueue, delivery_id: str = "delivery-1"):
        return queue.enqueue(
            delivery_id=delivery_id,
            tenant_id="kubernetes",
            repository="example/support",
            issue_number=42,
            issue_url="https://github.com/example/support/issues/42",
            ticket="How do I expose this service internally?",
            draft=sample_draft(),
        )

    def test_review_decision_and_duplicate_survive_restart(self) -> None:
        first_queue = PostgreSQLReviewQueue(self.dsn)
        self.assertTrue(first_queue.begin_delivery("delivery-1")[1])
        record, created = self.enqueue(first_queue)
        self.assertTrue(created)
        approved = first_queue.decide(
            record.review_id,
            "kubernetes",
            "approve",
            "Use an internal ClusterIP service.",
        )
        self.assertEqual(approved.status, "approved")

        restarted_queue = PostgreSQLReviewQueue(self.dsn)
        duplicate, claimed = restarted_queue.begin_delivery("delivery-1")

        self.assertFalse(claimed)
        self.assertEqual(duplicate.review_id, record.review_id)
        self.assertEqual(duplicate.final_answer, "Use an internal ClusterIP service.")
        self.assertEqual(restarted_queue.storage_name, "postgresql")

    def test_delivery_claim_is_atomic_across_connections(self) -> None:
        queue = PostgreSQLReviewQueue(self.dsn)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: queue.begin_delivery("simultaneous-delivery"),
                    range(2),
                )
            )

        self.assertEqual(sum(claimed for _, claimed in results), 1)

    def test_expired_claim_recovers_and_tenant_access_is_isolated(self) -> None:
        now = [1_000.0]
        queue = PostgreSQLReviewQueue(
            self.dsn,
            claim_ttl_seconds=300,
            clock=lambda: now[0],
        )
        self.assertTrue(queue.begin_delivery("crashed-delivery")[1])
        self.assertFalse(queue.begin_delivery("crashed-delivery")[1])
        now[0] += 301
        self.assertTrue(queue.begin_delivery("crashed-delivery")[1])

        record, _ = self.enqueue(queue, "tenant-delivery")
        self.assertIsNone(queue.get_for_tenant(record.review_id, "other"))
        with self.assertRaises(KeyError):
            queue.decide(record.review_id, "other", "reject", None)

    def test_schema_version_and_corrupt_draft_fail_closed(self) -> None:
        queue = PostgreSQLReviewQueue(self.dsn)
        record, _ = self.enqueue(queue)
        with self.psycopg.connect(self.dsn) as connection:
            connection.execute(
                """
                UPDATE support_copilot.reviews SET draft_json = 'not-json'
                WHERE review_id = %s
                """,
                (record.review_id,),
            )
        with self.assertRaisesRegex(RuntimeError, "stored review draft is invalid"):
            queue.list_for_tenant("kubernetes")

        with self.psycopg.connect(self.dsn) as connection:
            connection.execute(
                """
                UPDATE support_copilot.schema_versions SET version = 999
                WHERE component = 'github_review'
                """
            )
        with self.assertRaisesRegex(RuntimeError, "newer than supported"):
            PostgreSQLReviewQueue(self.dsn)

    def test_concurrent_initialization_is_migration_safe(self) -> None:
        with ThreadPoolExecutor(max_workers=2) as executor:
            queues = list(
                executor.map(lambda _: PostgreSQLReviewQueue(self.dsn), range(2))
            )

        self.assertEqual([queue.storage_name for queue in queues], ["postgresql"] * 2)

    def test_incomplete_current_schema_is_rejected(self) -> None:
        with self.psycopg.connect(self.dsn) as connection:
            connection.execute("CREATE SCHEMA support_copilot")
            connection.execute(
                """
                CREATE TABLE support_copilot.schema_versions (
                    component TEXT PRIMARY KEY,
                    version INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO support_copilot.schema_versions VALUES
                    ('github_review', 1)
                """
            )
            connection.execute(
                "CREATE TABLE support_copilot.reviews (review_id TEXT)"
            )
            connection.execute(
                "CREATE TABLE support_copilot.delivery_claims (delivery_id TEXT)"
            )

        with self.assertRaisesRegex(RuntimeError, "schema is incomplete"):
            PostgreSQLReviewQueue(self.dsn)

    def test_remote_database_requires_tls(self) -> None:
        with self.assertRaisesRegex(ValueError, "must require TLS"):
            PostgreSQLReviewQueue(
                "postgresql://user:password@database.example.com/reviews"
            )

    def test_api_reports_review_only_postgresql_storage(self) -> None:
        client = TestClient(
            create_app(
                KnowledgeBase(
                    [
                        KnowledgeDocument(
                            "service",
                            "Kubernetes Service",
                            "ClusterIP provides an internal service address.",
                            "https://kubernetes.io/docs/concepts/services-networking/service/",
                            tenant_id="kubernetes",
                        )
                    ]
                ),
                {"test-key": "kubernetes"},
                github_webhook_secret="test-webhook-secret-value",
                github_repositories={"example/support": "kubernetes"},
                github_review_database_url=self.dsn,
                review_api_keys={"review-key": "kubernetes"},
            )
        )

        readiness = client.get("/readyz").json()
        self.assertEqual(readiness["github_integration"], "review_only")
        self.assertEqual(readiness["github_review_storage"], "postgresql")
        self.assertEqual(readiness["github_posting"], "disabled")


if __name__ == "__main__":
    unittest.main()
