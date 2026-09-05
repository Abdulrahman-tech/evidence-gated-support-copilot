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
    EVIDENCE_RESPONSE_SCHEMA,
    EVIDENCE_SYSTEM_INSTRUCTIONS,
    EVIDENCE_VERIFIER_VERSION,
    EvidenceClaim,
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


def evaluation_configuration(
    provider: str,
    model: str,
    development_sha256: str,
    knowledge_sha256: str,
    candidate_inputs_sha256: str,
    case_ids: list[str],
) -> dict[str, object]:
    """Describe every input that must match before predictions can be reused."""

    prompt_sha256 = hashlib.sha256(
        EVIDENCE_SYSTEM_INSTRUCTIONS.encode("utf-8")
    ).hexdigest()
    schema_sha256 = hashlib.sha256(
        json.dumps(EVIDENCE_RESPONSE_SCHEMA, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "provider": provider,
        "model": model,
        "verifier_version": EVIDENCE_VERIFIER_VERSION,
        "split": "development",
        "development_sha256": development_sha256,
        "knowledge_sha256": knowledge_sha256,
        "candidate_inputs_sha256": candidate_inputs_sha256,
        "candidate_limit": EVIDENCE_CANDIDATE_LIMIT,
        "prompt_sha256": prompt_sha256,
        "schema_sha256": schema_sha256,
        "case_ids": case_ids,
    }


def load_checkpoint(
    path: Path,
    expected_configuration: dict[str, object],
) -> tuple[dict[str, dict[str, object]], set[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("evidence checkpoint is unreadable") from error
    if payload.get("configuration") != expected_configuration:
        raise ValueError("evidence checkpoint configuration does not match this run")
    raw_predictions = payload.get("predictions")
    if not isinstance(raw_predictions, list):
        raise ValueError("evidence checkpoint predictions must be a list")
    records: dict[str, dict[str, object]] = {}
    allowed_case_ids = set(expected_configuration["case_ids"])
    for record in raw_predictions:
        if not isinstance(record, dict) or not isinstance(record.get("case_id"), str):
            raise ValueError("evidence checkpoint contains an invalid prediction")
        case_id = record["case_id"]
        if case_id not in allowed_case_ids or case_id in records:
            raise ValueError("evidence checkpoint contains an unexpected case ID")
        records[case_id] = record
    fingerprints = payload.get("system_fingerprints", [])
    if not isinstance(fingerprints, list) or not all(
        isinstance(value, str) for value in fingerprints
    ):
        raise ValueError("evidence checkpoint fingerprints must be strings")
    return records, set(fingerprints)


def write_checkpoint(
    path: Path,
    configuration: dict[str, object],
    records: dict[str, dict[str, object]],
    system_fingerprints: set[str],
    *,
    complete: bool,
) -> None:
    ordered_records = [
        records[case_id]
        for case_id in configuration["case_ids"]
        if case_id in records
    ]
    ordered_fingerprints = sorted(system_fingerprints)
    payload = {
        # Preserve the original top-level metadata for existing result readers.
        "provider": configuration["provider"],
        "model": configuration["model"],
        "verifier_version": configuration["verifier_version"],
        "split": configuration["split"],
        "case_count": len(configuration["case_ids"]),
        "development_sha256": configuration["development_sha256"],
        "knowledge_sha256": configuration["knowledge_sha256"],
        "configuration": configuration,
        "complete": complete,
        "completed_case_count": len(ordered_records),
        "verifier_failures": sum(
            bool(record.get("verifier_failure")) for record in ordered_records
        ),
        "system_fingerprint": (
            ordered_fingerprints[0] if len(ordered_fingerprints) == 1 else None
        ),
        "system_fingerprints": ordered_fingerprints,
        "predictions": ordered_records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def verification_from_record(record: dict[str, object]) -> EvidenceVerification:
    decision = EvidenceDecision(record.get("decision"))
    raw_claims = record.get("claims")
    reason = record.get("reason")
    if not isinstance(raw_claims, list) or not isinstance(reason, str):
        raise ValueError("evidence checkpoint prediction has invalid fields")
    claims = []
    for claim in raw_claims:
        if not isinstance(claim, dict) or set(claim) != {"document_id", "quote"}:
            raise ValueError("evidence checkpoint claim is invalid")
        document_id = claim["document_id"]
        quote = claim["quote"]
        if not isinstance(document_id, str) or not isinstance(quote, str):
            raise ValueError("evidence checkpoint claim fields must be strings")
        claims.append(EvidenceClaim(document_id=document_id, quote=quote))
    return EvidenceVerification(decision=decision, claims=tuple(claims), reason=reason)


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
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse a configuration-matched partial checkpoint.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing output instead of resuming it.",
    )
    args = parser.parse_args()
    if args.max_cases is not None and args.max_cases <= 0:
        raise SystemExit("--max-cases must be positive")
    if args.start_index < 0:
        raise SystemExit("--start-index cannot be negative")
    if args.max_cases is not None and args.case_id:
        raise SystemExit("--max-cases and --case-id cannot be combined")
    if args.start_index and args.max_cases is None:
        raise SystemExit("--start-index requires --max-cases")
    if args.resume and args.overwrite:
        raise SystemExit("--resume and --overwrite cannot be combined")
    if args.resume and args.output is None:
        raise SystemExit("--resume requires --output")
    if args.output and args.output.exists() and not (args.resume or args.overwrite):
        raise SystemExit("output already exists; pass --resume or --overwrite")
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
    candidates_by_case = {
        case.case_id: knowledge_base.search(
            case.question,
            limit=EVIDENCE_CANDIDATE_LIMIT,
        )
        for case in cases
    }
    candidate_inputs = [
        {
            "case_id": case.case_id,
            "question": case.question,
            "candidates": [
                {
                    "document_id": candidate.document_id,
                    "title": candidate.title,
                    "passage": candidate.passage,
                }
                for candidate in candidates_by_case[case.case_id]
            ],
        }
        for case in cases
    ]
    candidate_inputs_sha256 = hashlib.sha256(
        json.dumps(
            candidate_inputs,
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    configuration = evaluation_configuration(
        provider,
        model,
        sha256(development_path),
        sha256(knowledge_path),
        candidate_inputs_sha256,
        [case.case_id for case in cases],
    )
    records: dict[str, dict[str, object]] = {}
    system_fingerprints: set[str] = set()
    if args.resume and args.output:
        try:
            records, system_fingerprints = load_checkpoint(
                args.output,
                configuration,
            )
        except ValueError as error:
            raise SystemExit(str(error)) from error

    predictions = []
    for case in cases:
        candidates = candidates_by_case[case.case_id]
        if case.case_id in records:
            try:
                prediction = verification_from_record(records[case.case_id])
                validate_verification(prediction, candidates)
            except ValueError as error:
                raise SystemExit(
                    f"checkpoint prediction for {case.case_id} is invalid: {error}"
                ) from error
            predictions.append(prediction)
            continue
        try:
            prediction = verifier.verify(case.question, candidates)
            validate_verification(prediction, candidates)
        except Exception as error:
            if type(error).__name__ == "RateLimitError":
                if args.output:
                    write_checkpoint(
                        args.output,
                        configuration,
                        records,
                        system_fingerprints,
                        complete=False,
                    )
                raise SystemExit(
                    f"{provider} rate limit reached after {len(records)}/{len(cases)} "
                    "cases. Wait for quota to reset, then rerun with --resume."
                ) from error
            failure_reason = f"verifier failure: {type(error).__name__}"
            if isinstance(error, ValueError):
                failure_reason = f"{failure_reason}: {error}"
            prediction = EvidenceVerification(
                decision=EvidenceDecision.UNCERTAIN,
                reason=failure_reason,
            )
        predictions.append(prediction)
        records[case.case_id] = {
            "case_id": case.case_id,
            "decision": prediction.decision.value,
            "claims": [
                {"document_id": claim.document_id, "quote": claim.quote}
                for claim in prediction.claims
            ],
            "reason": prediction.reason,
            "verifier_failure": prediction.reason.startswith("verifier failure:"),
        }
        fingerprint = getattr(verifier, "last_system_fingerprint", None)
        if fingerprint:
            system_fingerprints.add(fingerprint)
        if args.output:
            write_checkpoint(
                args.output,
                configuration,
                records,
                system_fingerprints,
                complete=False,
            )

    verifier_failures = sum(
        bool(record.get("verifier_failure")) for record in records.values()
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
        write_checkpoint(
            args.output,
            configuration,
            records,
            system_fingerprints,
            complete=True,
        )


if __name__ == "__main__":
    main()
