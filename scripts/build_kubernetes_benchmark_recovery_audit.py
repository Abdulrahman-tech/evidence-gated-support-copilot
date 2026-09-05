#!/usr/bin/env python3
"""Build the label-free Kubernetes benchmark-recovery source audit."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from support_copilot.medusa_discussions import near_duplicate
from support_copilot.scope import KubernetesScopeRouter


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "kubernetes"
BOOTSTRAP = DATA / "benchmark_bootstrap_historical"
SOURCE_POOL = DATA / "benchmark_source_pool"
OLD_PILOT = DATA / "source_yield_pilot"
OUTPUT = DATA / "benchmark_recovery_audit"
SEED = "kubernetes-benchmark-recovery-source-audit-v1"
PER_STRATUM = 10
EXTERNAL_TAG_PREFIXES = (
    "amazon-",
    "apache-",
    "argocd",
    "azure-",
    "docker",
    "google-",
    "istio",
    "java",
    "kubernetes-helm",
    "nginx",
    "node.js",
    "python",
    "spring-",
)


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_key(case_id: str, purpose: str) -> str:
    return hashlib.sha256(f"{SEED}:{purpose}:{case_id}".encode()).hexdigest()


def has_external_tag(tags: list[str]) -> bool:
    return any(
        tag == prefix or tag.startswith(prefix)
        for tag in tags
        for prefix in EXTERNAL_TAG_PREFIXES
    )


def diverse(rows: list[dict], count: int, purpose: str) -> list[dict]:
    selected: list[dict] = []
    for row in sorted(rows, key=lambda item: stable_key(item["case_id"], purpose)):
        if any(near_duplicate(row["question"], item["question"], 0.75) for item in selected):
            continue
        selected.append(row)
        if len(selected) == count:
            return selected
    raise ValueError(f"only {len(selected)} diverse {purpose} candidates available")


def select_unsupported(rows: list[dict], router: KubernetesScopeRouter) -> list[dict]:
    by_route: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        route = router.route(row["question"])
        if not route.in_scope:
            by_route[route.name].append(row)
    selected = [
        min(bucket, key=lambda row: stable_key(row["case_id"], route))
        for route, bucket in sorted(by_route.items())
    ]
    selected = diverse(selected, min(len(selected), PER_STRATUM), "unsupported-routes")
    if len(selected) < PER_STRATUM:
        selected_ids = {row["case_id"] for row in selected}
        remaining = sorted(
            [
            row
            for bucket in by_route.values()
            for row in bucket
            if row["case_id"] not in selected_ids
            ],
            key=lambda row: stable_key(row["case_id"], "unsupported-fill"),
        )
        for row in remaining:
            if any(near_duplicate(row["question"], item["question"], 0.75) for item in selected):
                continue
            selected.append(row)
            if len(selected) == PER_STRATUM:
                break
    if len(selected) != PER_STRATUM:
        raise ValueError("unsupported stratum did not reach its target")
    return selected


def build() -> tuple[list[dict], dict]:
    candidates_path = BOOTSTRAP / "accepted_answer_doc_links.json"
    bootstrap_manifest_path = BOOTSTRAP / "manifest.json"
    challenge_path = SOURCE_POOL / "challenge_questions.json"
    source_manifest_path = SOURCE_POOL / "manifest.json"
    old_pilot_path = OLD_PILOT / "review_packet.json"
    knowledge_path = DATA / "knowledge.json"

    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    bootstrap_manifest = json.loads(bootstrap_manifest_path.read_text(encoding="utf-8"))
    challenges = json.loads(challenge_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    old_pilot = json.loads(old_pilot_path.read_text(encoding="utf-8"))
    old_ids = {row["case_id"] for row in old_pilot}
    router = KubernetesScopeRouter()

    if sha256(candidates_path) != bootstrap_manifest["candidate_sha256"]:
        raise ValueError("accepted-answer bootstrap checksum mismatch")
    if sha256(challenge_path) != source_manifest["challenge_sha256"]:
        raise ValueError("challenge source-pool checksum mismatch")
    if sha256(knowledge_path) != bootstrap_manifest["knowledge_sha256"]:
        raise ValueError("Kubernetes knowledge checksum mismatch")
    if sha256(old_pilot_path) != bootstrap_manifest["pilot_sha256"]:
        raise ValueError("excluded source-yield pilot checksum mismatch")

    supported_pool = [
        row
        for row in candidates
        if row["anchor_mapping_status"] == "single_candidate"
        and router.route(row["question"]).in_scope
        and not has_external_tag(row["source_tags"])
        and row["case_id"] not in old_ids
    ]
    supported = diverse(supported_pool, PER_STRATUM, "supported-anchor")
    unsupported = select_unsupported(
        [row for row in challenges if row["case_id"] not in old_ids], router
    )
    selected = [(row, "supported_anchor") for row in supported] + [
        (row, "unsupported_scope") for row in unsupported
    ]
    if len({row["case_id"] for row, _ in selected}) != 2 * PER_STRATUM:
        raise ValueError("audit case IDs must be unique")
    if len({row["source_url"] for row, _ in selected}) != 2 * PER_STRATUM:
        raise ValueError("audit source URLs must be unique")

    shuffled = sorted(selected, key=lambda item: stable_key(item[0]["case_id"], "shuffle"))
    packet = [
        {
            "case_id": row["case_id"],
            "content_license": (
                row["content_license"]
                if "content_license" in row
                else row["accepted_answer_content_license"]
            ),
            "expected_document_id": "",
            "question": row["question"],
            "review_order": index,
            "review_status": "pending",
            "reviewer_decision": "",
            "reviewer_notes": "",
            "source_url": row["source_url"],
        }
        for index, (row, _) in enumerate(shuffled, start=1)
    ]
    packet_bytes = encoded(packet)
    selection_fingerprint = hashlib.sha256(
        encoded(sorted((row["case_id"], stratum) for row, stratum in selected))
    ).hexdigest()
    manifest = {
        "audit_id": "kubernetes_benchmark_recovery_source_audit_v1",
        "status": "awaiting_blind_human_review",
        "role": "source_filter_audit_excluded_from_all_evaluation_splits",
        "case_count": len(packet),
        "hidden_stratum_counts": {
            "supported_anchor": PER_STRATUM,
            "unsupported_scope": PER_STRATUM,
        },
        "selection_seed": SEED,
        "selection_fingerprint": selection_fingerprint,
        "selection_policy": (
            "Ten in-scope questions whose accepted answer links to one exact corpus "
            "anchor, and ten unanswered questions explicitly routed outside Kubernetes core."
        ),
        "review_policy": (
            "Review full source pages against the pinned official Kubernetes corpus. "
            "Accepted-answer links, routing strata, retrieval output, model predictions, "
            "and suggested labels are absent from the review packet."
        ),
        "packet_sha256": hashlib.sha256(packet_bytes).hexdigest(),
        "knowledge_sha256": sha256(knowledge_path),
        "bootstrap_candidates_sha256": sha256(candidates_path),
        "challenge_pool_sha256": sha256(challenge_path),
        "excluded_prior_pilot_sha256": sha256(old_pilot_path),
        "hosted_model_calls": 0,
        "locked_test_created": False,
        "evaluation_labels_created": False,
    }
    return packet, manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if OUTPUT.exists() and not args.rebuild:
        raise SystemExit("recovery audit already exists; pass --rebuild only before review")
    packet, manifest = build()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "review_packet.json").write_bytes(encoded(packet))
    (OUTPUT / "manifest.json").write_bytes(encoded(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
