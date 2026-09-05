#!/usr/bin/env python3
"""Evaluate the frozen semantic gate after blind human review of the issue pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from support_copilot.evaluation import wilson_interval
from support_copilot.knowledge import KnowledgeBase
from support_copilot.models import KnowledgeDocument
try:
    from scripts.evaluate_medusa_evidence_alignment import (
        alignment_features,
        document_frequency,
    )
except ModuleNotFoundError:  # Direct execution places scripts/ first on sys.path.
    from evaluate_medusa_evidence_alignment import alignment_features, document_frequency


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "medusa"
PILOT = DATA / "independent_validation_pilot"
BENCHMARK = DATA / "benchmark"
CALIBRATION = ROOT / "artifacts" / "medusa_local_semantic_gate.json"
OUTPUT = ROOT / "artifacts" / "medusa_independent_validation_issue_pilot.json"
DECISIONS = {"supported", "unsupported", "ambiguous", "outdated"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if not files:
        raise ValueError("semantic model snapshot is empty")
    for item in files:
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
    return digest.hexdigest()


def encoded(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def blank_packet(rows: list[dict]) -> list[dict]:
    return [
        {
            **row,
            "expected_document_id": "",
            "review_status": "pending",
            "reviewer_decision": "",
            "reviewer_notes": "",
        }
        for row in rows
    ]


def validate_reviews(
    rows: list[dict],
    manifest: dict,
    attestation: dict,
    document_ids: set[str],
) -> None:
    if len(rows) != manifest["case_count"]:
        raise ValueError("review packet case count changed")
    if hashlib.sha256(encoded(blank_packet(rows))).hexdigest() != manifest["packet_sha256"]:
        raise ValueError("review packet identity or source fields changed")
    if attestation.get("reviewer_type") != "human":
        raise ValueError("reviewer_type must be human")
    if not attestation.get("reviewer_id", "").strip():
        raise ValueError("reviewer_id is required")
    if not attestation.get("completed_at", "").strip():
        raise ValueError("completed_at is required")
    if attestation.get("reviewed_without_model_or_retriever_outputs") is not True:
        raise ValueError("blind-review attestation is required")

    for row in rows:
        case_id = row["case_id"]
        if row.get("review_status", "").strip().lower() != "approved":
            raise ValueError(f"{case_id}: review_status must be approved")
        raw_decision = row.get("reviewer_decision", "")
        decision = raw_decision.strip().lower()
        document_id = row.get("expected_document_id", "").strip()
        if decision not in DECISIONS:
            raise ValueError(f"{case_id}: invalid reviewer_decision")
        if raw_decision != decision:
            raise ValueError(f"{case_id}: reviewer_decision must use canonical lowercase")
        if decision == "supported":
            if document_id not in document_ids:
                raise ValueError(f"{case_id}: supported decision needs a valid document ID")
        elif document_id:
            raise ValueError(f"{case_id}: only supported decisions may have a document ID")


def evaluate(model_cache: Path) -> dict:
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError(
            "independent semantic evaluation requires the optional semantic dependencies"
        ) from error

    rows = json.loads((PILOT / "review_packet.json").read_text(encoding="utf-8"))
    manifest = json.loads((PILOT / "manifest.json").read_text(encoding="utf-8"))
    frozen = json.loads((PILOT / "frozen_candidate.json").read_text(encoding="utf-8"))
    attestation = json.loads(
        (PILOT / "reviewer_attestation.json").read_text(encoding="utf-8")
    )
    knowledge_path = DATA / "knowledge_expanded.json"
    documents = [
        KnowledgeDocument(**row)
        for row in json.loads(knowledge_path.read_text(encoding="utf-8"))
    ]
    validate_reviews(rows, manifest, attestation, {doc.document_id for doc in documents})

    if sha256(CALIBRATION) != frozen["calibration_artifact_sha256"]:
        raise ValueError("frozen calibration artifact changed")
    if sha256(knowledge_path) != frozen["knowledge_sha256"]:
        raise ValueError("frozen knowledge corpus changed")
    for split, expected in manifest["protected_benchmark_hashes"].items():
        if sha256(BENCHMARK / f"{split}.json") != expected:
            raise ValueError(f"protected {split} benchmark changed")

    retained = [
        row for row in rows if row["reviewer_decision"] in {"supported", "unsupported"}
    ]
    if not retained:
        raise ValueError("review produced no supported or unsupported evaluation cases")
    knowledge_base = KnowledgeBase(documents)
    ranked = [
        knowledge_base.search(row["question"], limit=3, tenant_id="medusa")
        for row in retained
    ]
    frequencies = document_frequency(documents)
    lexical = [
        alignment_features(row["question"], results, frequencies, len(documents))
        for row, results in zip(retained, ranked)
    ]
    model = frozen["model"]
    snapshot = (
        model_cache
        / f"models--{model['name'].replace('/', '--')}"
        / "snapshots"
        / model["revision"]
    )
    if directory_sha256(snapshot) != model["snapshot_sha256"]:
        raise ValueError("pinned semantic model snapshot changed or is unavailable")
    encoder = SentenceTransformer(
        model["name"], revision=model["revision"], local_files_only=True
    )
    question_vectors = encoder.encode(
        [row["question"] for row in retained],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    candidate_texts = [
        f"{result.title}. {result.passage}" for results in ranked for result in results
    ]
    candidate_vectors = encoder.encode(
        candidate_texts, normalize_embeddings=True, show_progress_bar=False
    )
    semantic: list[float] = []
    offset = 0
    for question_vector, results in zip(question_vectors, ranked):
        vectors = candidate_vectors[offset : offset + len(results)]
        offset += len(results)
        semantic.append(round(float(np.max(vectors @ question_vector)), 6))

    thresholds = frozen["thresholds"]
    accepted = [
        round(title, 6) >= thresholds["minimum_title_alignment"]
        and round(evidence, 6) >= thresholds["minimum_evidence_alignment"]
        and similarity >= thresholds["minimum_semantic_similarity"]
        for (title, evidence), similarity in zip(lexical, semantic)
    ]
    supported = [
        index
        for index, row in enumerate(retained)
        if row["reviewer_decision"] == "supported"
    ]
    unsupported = [
        index
        for index, row in enumerate(retained)
        if row["reviewer_decision"] == "unsupported"
    ]
    hits_at_1 = sum(
        accepted[index]
        and ranked[index]
        and ranked[index][0].document_id == retained[index]["expected_document_id"]
        for index in supported
    )
    hits_at_3 = sum(
        accepted[index]
        and any(
            result.document_id == retained[index]["expected_document_id"]
            for result in ranked[index][:3]
        )
        for index in supported
    )
    abstentions = sum(not accepted[index] for index in unsupported)

    return {
        "candidate": frozen["candidate"],
        "pilot_id": manifest["pilot_id"],
        "status": "pilot_complete_not_production_qualified",
        "human_review_attested": True,
        "runtime_changed": False,
        "hosted_calls": 0,
        "locked_test_evaluated": False,
        "source_yield": {
            "reviewed": len(rows),
            "supported": len(supported),
            "unsupported": len(unsupported),
            "ambiguous": sum(row["reviewer_decision"] == "ambiguous" for row in rows),
            "outdated": sum(row["reviewer_decision"] == "outdated" for row in rows),
        },
        "metrics": {
            "supported_recall_at_1": hits_at_1 / len(supported) if supported else None,
            "supported_recall_at_3": hits_at_3 / len(supported) if supported else None,
            "supported_recall_at_3_95ci": (
                list(wilson_interval(hits_at_3, len(supported)))
                if supported
                else None
            ),
            "unsupported_abstention": abstentions / len(unsupported) if unsupported else None,
            "unsupported_abstention_95ci": (
                list(wilson_interval(abstentions, len(unsupported)))
                if unsupported
                else None
            ),
        },
        "production_qualification": {
            "passed": False,
            "reason": (
                "This 30-case issue pilot is a source-yield and abstention check, not "
                "the required independently reviewed supported and unsupported cohorts."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-cache",
        type=Path,
        default=Path.home() / ".cache" / "huggingface" / "hub",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.model_cache)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output}")
    print(rendered, end="")


if __name__ == "__main__":
    main()
