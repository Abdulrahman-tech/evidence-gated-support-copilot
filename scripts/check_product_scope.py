#!/usr/bin/env python3
"""Fail CI when the declared Kubernetes product scope drifts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config" / "product_scope.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_scope(root: Path = ROOT) -> dict:
    contract = json.loads((root / "config" / "product_scope.json").read_text())
    manifest = json.loads((root / "data" / "kubernetes" / "manifest.json").read_text())
    medusa_pilot = json.loads(
        (
            root
            / "data"
            / "medusa"
            / "independent_validation_pilot"
            / "manifest.json"
        ).read_text()
    )
    dockerfile = (root / "Dockerfile").read_text()
    render = (root / "render.yaml").read_text()
    readme = (root / "README.md").read_text()
    medusa_scope = (root / "docs" / "medusa_scope.md").read_text()

    expected_path = contract["runtime_knowledge_path"]
    checks = {
        "primary_product_is_kubernetes": (
            contract["primary_product"] == "kubernetes_core_support_copilot"
            and contract["primary_tenant"] == "kubernetes"
        ),
        "kubernetes_corpus_is_pinned": (
            manifest["tenant_id"] == contract["primary_tenant"]
            and manifest["source_commit"] == contract["source_commit"]
            and sha256(root / "data" / "kubernetes" / "knowledge.json")
            == contract["runtime_knowledge_sha256"]
            == manifest["knowledge_sha256"]
        ),
        "docker_uses_kubernetes_only": (
            expected_path in dockerfile
            and "COPY data/kubernetes/knowledge.json" in dockerfile
            and "data/medusa" not in dockerfile
        ),
        "render_uses_kubernetes_only": (
            expected_path in render
            and 'value: \'{"local-demo-key":"kubernetes"}\'' in render
            and "data/medusa" not in render
        ),
        "public_claim_is_honest": (
            "production-minded portfolio beta, not production ready" in readme.lower()
        ),
        "medusa_is_not_a_production_track": (
            contract["experimental_tracks"]["medusa"] == "paused_offline_research"
            and medusa_pilot["status"] == "paused_scope_archive"
            and "Medusa production track" not in readme
            and "The production track supports" not in medusa_scope
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "status": "passed" if not failures else "failed",
        "primary_product": contract["primary_product"],
        "primary_tenant": contract["primary_tenant"],
        "checks": checks,
        "failures": failures,
    }


def main() -> None:
    result = audit_scope()
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
