import hashlib
import json
import unittest

from scripts.build_kubernetes_benchmark_recovery_audit import (
    DATA,
    OLD_PILOT,
    OUTPUT,
    build,
    encoded,
)


class KubernetesBenchmarkRecoveryTests(unittest.TestCase):
    def test_packet_is_deterministic_blind_and_excludes_prior_pilot(self) -> None:
        packet, manifest = build()
        persisted = json.loads((OUTPUT / "review_packet.json").read_text())
        old_ids = {
            row["case_id"]
            for row in json.loads((OLD_PILOT / "review_packet.json").read_text())
        }

        self.assertEqual(packet, persisted)
        self.assertEqual(len(packet), 20)
        self.assertEqual(len({row["case_id"] for row in packet}), 20)
        self.assertFalse({row["case_id"] for row in packet} & old_ids)
        self.assertEqual(
            set(packet[0]),
            {
                "case_id",
                "content_license",
                "expected_document_id",
                "question",
                "review_order",
                "review_status",
                "reviewer_decision",
                "reviewer_notes",
                "source_url",
            },
        )
        for row in packet:
            self.assertEqual(row["reviewer_decision"], "")
            self.assertEqual(row["expected_document_id"], "")
            self.assertEqual(row["review_status"], "pending")
            self.assertNotIn("label", row)
            self.assertNotIn("prediction", row)
            self.assertNotIn("stratum", row)
            self.assertTrue(row["source_url"].startswith("https://stackoverflow.com/"))

        self.assertEqual(
            manifest["role"],
            "source_filter_audit_excluded_from_all_evaluation_splits",
        )
        self.assertFalse(manifest["locked_test_created"])
        self.assertFalse(manifest["evaluation_labels_created"])
        self.assertEqual(manifest["hosted_model_calls"], 0)

    def test_manifest_matches_rebuilt_inputs(self) -> None:
        _, rebuilt = build()
        persisted = json.loads((OUTPUT / "manifest.json").read_text())

        self.assertEqual(encoded(rebuilt), encoded(persisted))
        self.assertEqual(
            persisted["knowledge_sha256"],
            hashlib.sha256((DATA / "knowledge.json").read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
