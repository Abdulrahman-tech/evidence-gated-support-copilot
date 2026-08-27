#!/usr/bin/env python3
"""Record the AI-assisted source audit for six Helm-routed pilot cases."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELM_ROOT = ROOT / "data" / "helm" / "v3"
DIAGNOSTIC = ROOT / "artifacts" / "helm_v3_pilot_retrieval_diagnostic_20260826.json"
OUTPUT_DIR = HELM_ROOT / "qualification"


DECISIONS = {
    "stackoverflow-kubernetes-79801711": {
        "decision": "unsupported",
        "expected_document_id": None,
        "evidence_quote": None,
        "note": (
            "The full source is resolved by Kubernetes Service DNS/FQDN behavior and Mongo "
            "connectivity; Helm documentation only helps render the template for inspection."
        ),
    },
    "stackoverflow-kubernetes-79525781": {
        "decision": "unsupported",
        "expected_document_id": None,
        "evidence_quote": None,
        "note": (
            "The fix requires the GoCD chart-specific agent.replicaCount value path, which is "
            "not documented in the official Helm corpus."
        ),
    },
    "stackoverflow-kubernetes-79464712": {
        "decision": "supported",
        "expected_document_id": "helm3-88f12d32e97a3e2e",
        "evidence_quote": (
            "More complex expressions are supported. For example, --set outer.inner=value\n"
            "is translated into this:"
        ),
        "note": (
            "The official --set documentation directly explains that a dotted key creates a "
            "nested value, which is why image.registry changed image from a string into a map."
        ),
    },
    "stackoverflow-kubernetes-79465457": {
        "decision": "unsupported",
        "expected_document_id": None,
        "evidence_quote": None,
        "note": (
            "The answer requires container entrypoint or Tomcat environment-variable composition; "
            "the pinned Helm corpus does not directly document that runtime behavior."
        ),
    },
    "stackoverflow-kubernetes-79663394": {
        "decision": "supported",
        "expected_document_id": "helm3-21e4076d6bc030ce",
        "evidence_quote": (
            "{{-  (with\nthe dash and space added) indicates that whitespace should be chomped "
            "left,\nwhile  -}} means whitespace to the right should be consumed."
        ),
        "note": (
            "The official whitespace-control section directly explains that {{- removes left "
            "whitespace, causing the malformed YAML after the colon."
        ),
    },
    "stackoverflow-kubernetes-79346457": {
        "decision": "unsupported",
        "expected_document_id": None,
        "evidence_quote": None,
        "note": (
            "The working configuration is Tanka's skipTests wrapper option. Helm documents the "
            "CLI --skip-tests flag but not the required Tanka/Jsonnet syntax."
        ),
    },
}


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    diagnostic = json.loads(DIAGNOSTIC.read_text(encoding="utf-8"))
    knowledge_path = HELM_ROOT / "knowledge.json"
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    documents_by_id = {row["document_id"]: row for row in knowledge}
    cases_by_id = {row["case_id"]: row for row in diagnostic["cases"]}
    if set(cases_by_id) != set(DECISIONS):
        raise ValueError("audit decisions do not match the frozen Helm diagnostic cases")

    rows = []
    for case_id, case in cases_by_id.items():
        decision = DECISIONS[case_id]
        document_id = decision["expected_document_id"]
        quote = decision["evidence_quote"]
        if decision["decision"] == "supported":
            document = documents_by_id.get(document_id)
            if document is None or quote not in document["text"]:
                raise ValueError(f"invalid supported evidence for {case_id}")
        elif document_id is not None or quote is not None:
            raise ValueError(f"unsupported case {case_id} cannot contain evidence")

        candidate_ids = [item["document_id"] for item in case["candidates"]]
        rows.append(
            {
                "case_id": case_id,
                "source_url": case["source_url"],
                "question": case["question"],
                "source_content_checked": True,
                "reviewer_decision": decision["decision"],
                "expected_document_id": document_id,
                "evidence_quote": quote,
                "retrieval_rank": (
                    candidate_ids.index(document_id) + 1
                    if document_id in candidate_ids
                    else None
                ),
                "review_status": "approved",
                "reviewer_notes": decision["note"],
                "review_method": "ai_source_content_audit_codex",
            }
        )

    counts = Counter(row["reviewer_decision"] for row in rows)
    supported = [row for row in rows if row["reviewer_decision"] == "supported"]
    unsupported = [row for row in rows if row["reviewer_decision"] == "unsupported"]
    top1 = sum(row["retrieval_rank"] == 1 for row in supported)
    top3 = sum(
        row["retrieval_rank"] is not None and row["retrieval_rank"] <= 3
        for row in supported
    )
    unsupported_abstained = sum(
        not cases_by_id[row["case_id"]]["legacy_threshold_confident"]
        for row in unsupported
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = OUTPUT_DIR / "pilot_source_audit.json"
    audit_bytes = encoded(rows)
    audit_path.write_bytes(audit_bytes)
    manifest = {
        "audit_id": "helm_v3_pilot_source_audit_20260826",
        "role": "ai_assisted_diagnostic_excluded_from_evaluation",
        "review_provenance": (
            "Codex opened all six Stack Overflow sources and compared them with the pinned "
            "Helm 3 corpus. This is not independent human ground truth."
        ),
        "case_count": len(rows),
        "decision_counts": dict(sorted(counts.items())),
        "supported_recall_at_1": top1 / len(supported),
        "supported_recall_at_3": top3 / len(supported),
        "unsupported_legacy_threshold_abstention": (
            unsupported_abstained / len(unsupported)
        ),
        "helm_knowledge_sha256": sha256(knowledge_path),
        "retrieval_diagnostic_sha256": sha256(DIAGNOSTIC),
        "audit_sha256": hashlib.sha256(audit_bytes).hexdigest(),
        "hosted_model_calls": 0,
        "runtime_integration_allowed": False,
        "blocking_reason": (
            "The sample is tiny, Recall@3 is below a production gate, unsupported abstention is "
            "low, and the labels are AI-assisted diagnostics rather than independent validation."
        ),
    }
    (OUTPUT_DIR / "manifest.json").write_bytes(encoded(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
