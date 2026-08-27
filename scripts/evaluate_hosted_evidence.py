#!/usr/bin/env python3
"""Shared development-only evaluation for hosted evidence verifiers."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from support_copilot.evaluation import (
    evidence_verification_metrics,
    load_cases,
    wilson_interval,
)
from support_copilot.evidence import (
    EVIDENCE_VERIFIER_VERSION,
    EvidenceDecision,
    EvidenceVerification,
    EvidenceVerifier,
    validate_verification,
)
from support_copilot.groq_evidence import DEFAULT_GROQ_MODEL, GroqEvidenceVerifier
from support_copilot.knowledge import KnowledgeBase
from support_copilot.models import KnowledgeDocument
from support_copilot.openai_evidence import OpenAIEvidenceVerifier


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "medusa"
BENCHMARK_DIRECTORY = DATA_DIRECTORY / "benchmark"
EVIDENCE_CANDIDATE_LIMIT = 3


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configured_verifier(provider: str) -> tuple[str, EvidenceVerifier]:
    if provider == "groq":
        if not os.environ.get("GROQ_API_KEY"):
            raise SystemExit("GROQ_API_KEY is required")
        model = os.environ.get("SUPPORT_COPILOT_GROQ_MODEL", DEFAULT_GROQ_MODEL)
        return model, GroqEvidenceVerifier(model=model)
    model = os.environ.get("SUPPORT_COPILOT_OPENAI_MODEL")
    if not os.environ.get("OPENAI_API_KEY") or not model:
        raise SystemExit("OPENAI_API_KEY and SUPPORT_COPILOT_OPENAI_MODEL are required")
    return model, OpenAIEvidenceVerifier(model=model)


def main(provider: str | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="The validation and locked-test splits are deliberately unavailable."
    )
    if provider is None:
        parser.add_argument("--provider", choices=("groq", "openai"), required=True)
    parser.add_argument(
        "--max-cases",
        type=int,
        help="Run a development smoke test instead of the complete split.",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Zero-based development offset used with --max-cases.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        help="Evaluate only this development case; may be repeated.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.max_cases is not None and args.max_cases <= 0:
        raise SystemExit("--max-cases must be positive")
    if args.start_index < 0:
        raise SystemExit("--start-index cannot be negative")
    if args.max_cases is not None and args.case_id:
        raise SystemExit("--max-cases and --case-id cannot be combined")
    if args.start_index and args.max_cases is None:
        raise SystemExit("--start-index requires --max-cases")
    provider = provider or args.provider
    model, verifier = configured_verifier(provider)

    benchmark_manifest = json.loads(
        (BENCHMARK_DIRECTORY / "manifest.json").read_text(encoding="utf-8")
    )
    knowledge_manifest = json.loads(
        (DATA_DIRECTORY / "expanded_manifest.json").read_text(encoding="utf-8")
    )
    knowledge_path = DATA_DIRECTORY / "knowledge_expanded.json"
    development_path = BENCHMARK_DIRECTORY / "development.json"
    if sha256(knowledge_path) != knowledge_manifest["knowledge_sha256"]:
        raise SystemExit("Medusa knowledge checksum mismatch")
    if sha256(development_path) != benchmark_manifest["splits"]["development"]["sha256"]:
        raise SystemExit("Medusa development checksum mismatch")

    documents = [
        KnowledgeDocument(**item)
        for item in json.loads(knowledge_path.read_text(encoding="utf-8"))
    ]
    cases = load_cases(development_path)
    if args.case_id:
        cases_by_id = {case.case_id: case for case in cases}
        unknown_case_ids = set(args.case_id) - set(cases_by_id)
        if unknown_case_ids:
            raise SystemExit(f"unknown development case IDs: {sorted(unknown_case_ids)}")
        cases = [cases_by_id[case_id] for case_id in args.case_id]
    elif args.max_cases is not None:
        cases = cases[args.start_index : args.start_index + args.max_cases]
        if not cases:
            raise SystemExit("development case range is empty")

    knowledge_base = KnowledgeBase(documents)
    predictions = []
    records = []
    verifier_failures = 0
    for case in cases:
        candidates = knowledge_base.search(
            case.question,
            limit=EVIDENCE_CANDIDATE_LIMIT,
        )
        try:
            prediction = verifier.verify(case.question, candidates)
            validate_verification(prediction, candidates)
        except Exception as error:
            if type(error).__name__ == "RateLimitError":
                raise SystemExit(
                    f"{provider} rate limit reached; evaluation aborted without metrics. "
                    "Wait for the provider quota to reset before retrying."
                ) from error
            verifier_failures += 1
            failure_reason = f"verifier failure: {type(error).__name__}"
            if isinstance(error, ValueError):
                failure_reason = f"{failure_reason}: {error}"
            prediction = EvidenceVerification(
                decision=EvidenceDecision.UNCERTAIN,
                reason=failure_reason,
            )
        predictions.append(prediction)
        records.append(
            {
                "case_id": case.case_id,
                "decision": prediction.decision.value,
                "claims": [
                    {"document_id": claim.document_id, "quote": claim.quote}
                    for claim in prediction.claims
                ],
                "reason": prediction.reason,
            }
        )

    metrics = evidence_verification_metrics(cases, predictions)
    supported_total = sum(case.expected_document_id is not None for case in cases)
    unsupported_total = len(cases) - supported_total
    supported_predictions = sum(
        prediction.decision is EvidenceDecision.SUPPORTED
        for prediction in predictions
    )
    correct_supported = round(metrics.supported_recall * supported_total)
    unsupported_abstentions = round(
        metrics.unsupported_abstention_rate * unsupported_total
    )
    print(f"provider={provider}")
    print(f"model={model}")
    print(f"verifier_version={EVIDENCE_VERIFIER_VERSION}")
    print(f"development_cases={len(cases)}")
    print(f"verifier_failures={verifier_failures}")
    print(f"supported_precision={metrics.supported_precision:.3f}")
    if supported_predictions:
        lower, upper = wilson_interval(correct_supported, supported_predictions)
        print(f"supported_precision_95ci=[{lower:.3f},{upper:.3f}]")
    print(f"supported_recall={metrics.supported_recall:.3f}")
    if supported_total:
        lower, upper = wilson_interval(correct_supported, supported_total)
        print(f"supported_recall_95ci=[{lower:.3f},{upper:.3f}]")
    print(f"unsupported_abstention_rate={metrics.unsupported_abstention_rate:.3f}")
    if unsupported_total:
        lower, upper = wilson_interval(unsupported_abstentions, unsupported_total)
        print(f"unsupported_abstention_rate_95ci=[{lower:.3f},{upper:.3f}]")

    if args.output:
        payload = {
            "provider": provider,
            "model": model,
            "verifier_version": EVIDENCE_VERIFIER_VERSION,
            "split": "development",
            "case_count": len(cases),
            "development_sha256": sha256(development_path),
            "knowledge_sha256": sha256(knowledge_path),
            "verifier_failures": verifier_failures,
            "system_fingerprint": getattr(verifier, "last_system_fingerprint", None),
            "predictions": records,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
