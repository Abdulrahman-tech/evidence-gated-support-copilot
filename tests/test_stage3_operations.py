import unittest

from scripts.check_live_service import REQUIRED_METRICS, validate_probe
from scripts.load_test_api import Result, percentile, summarize, validate_base_url


class Stage3OperationsTests(unittest.TestCase):
    def test_live_probe_contract_accepts_privacy_safe_metrics(self) -> None:
        metrics = "\n".join(f"{name} 0" for name in REQUIRED_METRICS)
        failures = validate_probe(
            {"status": "ok"},
            {"status": "ready", "evidence_verifier": "fail_closed"},
            metrics,
            {
                "cache-control": "no-store",
                "content-security-policy": "frame-ancestors 'none'",
                "referrer-policy": "no-referrer",
                "x-content-type-options": "nosniff",
                "x-frame-options": "DENY",
            },
        )

        self.assertEqual(failures, [])

    def test_live_probe_contract_fails_on_sensitive_labels_and_missing_headers(self) -> None:
        metrics = "\n".join(f"{name} 0" for name in REQUIRED_METRICS)
        failures = validate_probe(
            {"status": "ok"},
            {"status": "ready", "evidence_verifier": "fail_closed"},
            metrics + '\nsupport_copilot_requests{tenant="customer"} 1',
            {},
        )

        self.assertIn("sensitive metric label detected: tenant", failures)
        self.assertIn("missing or invalid security header: cache-control", failures)

    def test_load_test_rejects_remote_targets_without_explicit_opt_in(self) -> None:
        self.assertEqual(
            validate_base_url("http://127.0.0.1:8000/", False),
            "http://127.0.0.1:8000",
        )
        with self.assertRaisesRegex(ValueError, "--allow-remote"):
            validate_base_url("https://support.example.com", False)

    def test_load_summary_uses_nearest_rank_p95_and_counts_failures(self) -> None:
        self.assertEqual(percentile([0.1, 0.2, 0.3, 0.4], 0.95), 0.4)
        summary = summarize(
            [
                Result(200, 0.1, "supported"),
                Result(200, 0.2, "uncertain"),
                Result(429, 0.3, None),
            ]
        )

        self.assertAlmostEqual(summary["error_rate"], 1 / 3)
        self.assertEqual(summary["status_counts"], {"200": 2, "429": 1})
        self.assertEqual(summary["supported"], 1)
        self.assertEqual(summary["abstained"], 1)


if __name__ == "__main__":
    unittest.main()
