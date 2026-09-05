#!/usr/bin/env python3
"""Evaluate a pinned, offline semantic-alignment gate on Medusa development."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from support_copilot.evaluation import EvaluationCase, load_cases, wilson_interval
from support_copilot.knowledge import KnowledgeBase
from support_copilot.models import KnowledgeDocument, SearchResult
from evaluate_medusa_evidence_alignment import (
    BENCHMARK,
    EXPECTED_LOCKED_TEST_SHA256,
    EXPECTED_VALIDATION_SHA256,
    MEDUSA,
    MINIMUM_SUPPORTED_RECALL_AT_3,
    MINIMUM_UNSUPPORTED_ABSTENTION,
    ROOT,
    alignment_features,
    document_frequency,
    sha256,
)


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"


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


def measure(
    cases: list[EvaluationCase],
    ranked: list[list[SearchResult]],
    features: list[tuple[float, float, float]],
    minimum_title_alignment: float,
    minimum_evidence_alignment: float,
    minimum_semantic_similarity: float,
) -> dict[str, float | int]:
    supported_count = sum(case.expected_document_id is not None for case in cases)
    unsupported_count = len(cases) - supported_count
    accepted = [
        title >= minimum_title_alignment
        and evidence >= minimum_evidence_alignment
        and semantic >= minimum_semantic_similarity
        for title, evidence, semantic in features
    ]
    hits_at_1 = sum(
        is_accepted
        and results
        and results[0].document_id == case.expected_document_id
        for case, results, is_accepted in zip(cases, ranked, accepted)
        if case.expected_document_id is not None
    )
    hits_at_3 = sum(
        is_accepted
        and any(
            result.document_id == case.expected_document_id
            for result in results[:3]
        )
        for case, results, is_accepted in zip(cases, ranked, accepted)
        if case.expected_document_id is not None
    )
    unsupported_abstentions = sum(
        not is_accepted
        for case, is_accepted in zip(cases, accepted)
        if case.expected_document_id is None
    )
    return {
        "minimum_title_alignment": minimum_title_alignment,
        "minimum_evidence_alignment": minimum_evidence_alignment,
        "minimum_semantic_similarity": minimum_semantic_similarity,
        "supported_recall_at_1": hits_at_1 / supported_count,
        "supported_recall_at_3": hits_at_3 / supported_count,
        "unsupported_abstention": unsupported_abstentions / unsupported_count,
        "accepted_count": sum(accepted),
        "unsupported_pass_count": unsupported_count - unsupported_abstentions,
    }


def select_candidate(
    cases: list[EvaluationCase],
    ranked: list[list[SearchResult]],
    features: list[tuple[float, float, float]],
) -> tuple[dict[str, float | int] | None, int]:
    supported_hits = [
        feature
        for case, results, feature in zip(cases, ranked, features)
        if case.expected_document_id is not None
        and any(
            result.document_id == case.expected_document_id
            for result in results[:3]
        )
    ]
    thresholds = [sorted({0.0} | {row[index] for row in supported_hits}) for index in range(3)]
    candidates = [
        measure(cases, ranked, features, title, evidence, semantic)
        for title in thresholds[0]
        for evidence in thresholds[1]
        for semantic in thresholds[2]
    ]
    feasible = [
        candidate
        for candidate in candidates
        if candidate["supported_recall_at_3"] >= MINIMUM_SUPPORTED_RECALL_AT_3
        and candidate["unsupported_abstention"] >= MINIMUM_UNSUPPORTED_ABSTENTION
    ]
    if not feasible:
        return None, len(candidates)
    return (
        max(
            feasible,
            key=lambda candidate: (
                candidate["unsupported_abstention"],
                candidate["supported_recall_at_1"],
                -candidate["accepted_count"],
            ),
        ),
        len(candidates),
    )


def evaluate(model_cache: Path) -> dict:
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError(
            "local semantic evaluation requires the optional semantic dependencies"
        ) from error

    development_path = BENCHMARK / "development.json"
    validation_path = BENCHMARK / "validation.json"
    locked_test_path = BENCHMARK / "test.json"
    knowledge_path = MEDUSA / "knowledge_expanded.json"
    model_snapshot = (
        model_cache
        / f"models--{MODEL_NAME.replace('/', '--')}"
        / "snapshots"
        / MODEL_REVISION
    )
    benchmark_manifest = json.loads((BENCHMARK / "manifest.json").read_text())
    knowledge_manifest = json.loads((MEDUSA / "expanded_manifest.json").read_text())
    checksums = {
        "development": sha256(development_path),
        "validation": sha256(validation_path),
        "locked_test": sha256(locked_test_path),
        "knowledge": sha256(knowledge_path),
    }
    if checksums["development"] != benchmark_manifest["splits"]["development"]["sha256"]:
        raise ValueError("Medusa development checksum mismatch")
    if checksums["validation"] != EXPECTED_VALIDATION_SHA256:
        raise ValueError("protected validation split changed")
    if checksums["locked_test"] != EXPECTED_LOCKED_TEST_SHA256:
        raise ValueError("protected locked test changed")
    if checksums["knowledge"] != knowledge_manifest["knowledge_sha256"]:
        raise ValueError("Medusa knowledge checksum mismatch")
    if not model_snapshot.is_dir():
        raise ValueError("pinned semantic model is not available in the local cache")

    cases = load_cases(development_path)
    documents = [
        KnowledgeDocument(**row)
        for row in json.loads(knowledge_path.read_text(encoding="utf-8"))
    ]
    knowledge_base = KnowledgeBase(documents)
    ranked = [
        knowledge_base.search(case.question, limit=3, tenant_id="medusa")
        for case in cases
    ]
    frequencies = document_frequency(documents)
    lexical_features = [
        alignment_features(case.question, results, frequencies, len(documents))
        for case, results in zip(cases, ranked)
    ]
    model = SentenceTransformer(
        MODEL_NAME,
        revision=MODEL_REVISION,
        local_files_only=True,
    )
    question_vectors = model.encode(
        [case.question for case in cases],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    candidate_texts = [
        f"{result.title}. {result.passage}"
        for results in ranked
        for result in results
    ]
    candidate_vectors = model.encode(
        candidate_texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    semantic_features = []
    offset = 0
    for question_vector, results in zip(question_vectors, ranked):
        vectors = candidate_vectors[offset : offset + len(results)]
        offset += len(results)
        semantic_features.append(float(np.max(vectors @ question_vector)))
    features = [
        (round(title, 6), round(evidence, 6), round(semantic, 6))
        for (title, evidence), semantic in zip(lexical_features, semantic_features)
    ]
    selected, candidate_count = select_candidate(cases, ranked, features)
    supported_count = sum(case.expected_document_id is not None for case in cases)
    unsupported_count = len(cases) - supported_count
    recall_successes = (
        round(selected["supported_recall_at_3"] * supported_count) if selected else 0
    )
    abstention_successes = (
        round(selected["unsupported_abstention"] * unsupported_count)
        if selected
        else 0
    )
    recall_interval = wilson_interval(recall_successes, supported_count)
    abstention_interval = wilson_interval(abstention_successes, unsupported_count)

    return {
        "candidate": "local_semantic_alignment_v1",
        "calibration_scope": "medusa_development_only",
        "selection_status": (
            "selected_for_independent_validation" if selected else "rejected"
        ),
        "runtime_changed": False,
        "hosted_calls": 0,
        "model": {
            "name": MODEL_NAME,
            "revision": MODEL_REVISION,
            "snapshot_sha256": directory_sha256(model_snapshot),
            "local_files_only": True,
        },
        "requirements": {
            "minimum_supported_recall_at_3": MINIMUM_SUPPORTED_RECALL_AT_3,
            "minimum_unsupported_abstention": MINIMUM_UNSUPPORTED_ABSTENTION,
        },
        "selected": selected,
        "development_point_gates_passed": bool(selected),
        "development_uncertainty": {
            "supported_recall_at_3_95ci": list(recall_interval),
            "unsupported_abstention_95ci": list(abstention_interval),
            "production_confidence_gates_passed": False,
            "reason": "Only seven supported development cases are available.",
        },
        "development": {
            "case_count": len(cases),
            "supported_count": supported_count,
            "unsupported_count": unsupported_count,
            "sha256": checksums["development"],
        },
        "candidate_threshold_count": candidate_count,
        "knowledge_sha256": checksums["knowledge"],
        "protected_splits_evaluated": [],
        "protected_split_checksums": {
            "validation": checksums["validation"],
            "locked_test": checksums["locked_test"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-cache",
        type=Path,
        default=Path.home() / ".cache" / "huggingface" / "hub",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "medusa_local_semantic_gate.json",
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(evaluate(args.model_cache), indent=2, sort_keys=True) + "\n"
    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output}")
    print(rendered, end="")


if __name__ == "__main__":
    main()
