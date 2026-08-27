#!/usr/bin/env python3
"""Create a zero-token retrieval diagnostic for Helm-routed pilot titles."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.models import KnowledgeDocument
from support_copilot.scope import KubernetesScopeRouter


ROOT = Path(__file__).resolve().parents[1]
HELM_ROOT = ROOT / "data" / "helm" / "v3"
PILOT_PATH = ROOT / "data" / "kubernetes" / "source_yield_pilot" / "review_packet.json"
OUTPUT = ROOT / "artifacts" / "helm_v3_pilot_retrieval_diagnostic_20260826.json"


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    knowledge_path = HELM_ROOT / "knowledge.json"
    manifest = json.loads((HELM_ROOT / "manifest.json").read_text(encoding="utf-8"))
    if manifest["knowledge_sha256"] != sha256(knowledge_path):
        raise ValueError("Helm knowledge checksum mismatch")

    documents = [
        KnowledgeDocument(**row)
        for row in json.loads(knowledge_path.read_text(encoding="utf-8"))
    ]
    knowledge_base = KnowledgeBase(documents)
    router = KubernetesScopeRouter()
    pilot = json.loads(PILOT_PATH.read_text(encoding="utf-8"))
    helm_cases = [row for row in pilot if router.route(row["question"]).name == "helm"]

    cases = []
    for row in helm_cases:
        results = knowledge_base.search(
            row["question"],
            limit=3,
            tenant_id="helm-v3",
        )
        cases.append(
            {
                "case_id": row["case_id"],
                "question": row["question"],
                "source_url": row["source_url"],
                "source_tags": row["source_tags"],
                "legacy_threshold_confident": retrieval_is_confident(results),
                "candidates": [asdict(result) for result in results],
            }
        )

    report = {
        "diagnostic_id": "helm_v3_pilot_retrieval_diagnostic_20260826",
        "role": "unlabelled_diagnostic_excluded_from_evaluation",
        "interpretation": (
            "Candidate ranking only. Confidence uses the existing uncalibrated global threshold "
            "and must not be interpreted as Helm accuracy or approval."
        ),
        "helm_source_commit": manifest["source_commit"],
        "helm_source_version": manifest["source_version"],
        "helm_knowledge_sha256": manifest["knowledge_sha256"],
        "pilot_sha256": sha256(PILOT_PATH),
        "case_count": len(cases),
        "legacy_threshold_confident_count": sum(
            case["legacy_threshold_confident"] for case in cases
        ),
        "hosted_model_calls": 0,
        "cases": cases,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(encoded(report))
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
