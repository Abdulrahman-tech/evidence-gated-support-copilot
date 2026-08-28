"""Deterministic failure drills for the HTTP support workflow."""

import unittest

from fastapi.testclient import TestClient

from support_copilot.api import create_app
from support_copilot.evidence import (
    EvidenceClaim,
    EvidenceDecision,
    EvidenceVerification,
)
from support_copilot.knowledge import KnowledgeBase
from support_copilot.models import KnowledgeDocument


QUESTION = "Which Kubernetes Service type is reachable only within the cluster?"


def knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(
        [
            KnowledgeDocument(
                "cluster-ip",
                "Kubernetes Service type ClusterIP",
                "A ClusterIP Service is reachable only from within the cluster.",
                "https://kubernetes.io/docs/concepts/services-networking/service/",
                tenant_id="kubernetes",
            )
        ]
    )


def post_draft(client: TestClient):
    return client.post(
        "/v1/drafts",
        json={"ticket": QUESTION},
        headers={"Authorization": "Bearer test-key"},
    )


class TimeoutVerifier:
    provider_name = "failure_injection"

    def verify(self, question, candidates):
        del question, candidates
        timeout_error = type("APITimeoutError", (Exception,), {})
        raise timeout_error("simulated private provider detail")


class MalformedEvidenceVerifier:
    provider_name = "failure_injection"

    def verify(self, question, candidates):
        del question, candidates
        return EvidenceVerification(
            EvidenceDecision.SUPPORTED,
            (EvidenceClaim("cluster-ip", "A quote absent from the source passage."),),
        )


class FailureInjectionTests(unittest.TestCase):
    def test_provider_timeout_abstains_without_an_http_failure(self) -> None:
        client = TestClient(
            create_app(
                knowledge_base(),
                {"test-key": "kubernetes"},
                evidence_verifier=TimeoutVerifier(),
                minimum_score=0.1,
            )
        )

        response = post_draft(client)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["evidence_decision"], "uncertain")
        self.assertEqual(payload["citations"], [])
        self.assertTrue(payload["needs_human_review"])
        self.assertIn("evidence:provider_unavailable", payload["trajectory"])
        self.assertNotIn("simulated private provider detail", response.text)
        metrics = client.get("/metrics").text
        self.assertIn("support_copilot_drafts_abstained_total 1", metrics)
        self.assertIn("support_copilot_draft_failures_total 0", metrics)

    def test_malformed_evidence_abstains_instead_of_citing_it(self) -> None:
        client = TestClient(
            create_app(
                knowledge_base(),
                {"test-key": "kubernetes"},
                evidence_verifier=MalformedEvidenceVerifier(),
                minimum_score=0.1,
            )
        )

        response = post_draft(client)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["evidence_decision"], "uncertain")
        self.assertEqual(payload["citations"], [])
        self.assertIn("evidence:invalid_response", payload["trajectory"])

    def test_overload_rejection_does_not_break_health_or_readiness(self) -> None:
        client = TestClient(
            create_app(
                knowledge_base(),
                {"test-key": "kubernetes"},
                rate_limit_requests=1,
                rate_limit_window_seconds=60,
            )
        )

        self.assertEqual(post_draft(client).status_code, 200)
        limited = post_draft(client)

        self.assertEqual(limited.status_code, 429)
        self.assertGreaterEqual(int(limited.headers["retry-after"]), 1)
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.get("/readyz").json()["status"], "ready")


if __name__ == "__main__":
    unittest.main()
