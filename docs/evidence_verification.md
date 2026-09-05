# Evidence verification contract

Retrieval proposes documentation; it does not authorize an answer. A configured
evidence verifier must return exactly one of `supported`, `unsupported`, or
`uncertain` before the copilot can create a substantive draft.

The model adapter returns this JSON-shaped structure:

```json
{
  "decision": "supported",
  "claims": [
    {
      "document_id": "approved-candidate-id",
      "quote": "An exact quote copied from the retrieved passage."
    }
  ],
  "reason": "A short explanation of why the evidence answers the core question."
}
```

The application enforces these rules after the model responds:

- Only retrieved candidate document IDs are allowed.
- Every evidence quote must occur verbatim in its candidate passage.
- `supported` requires at least one evidence claim.
- `unsupported` and `uncertain` cannot include evidence claims.
- Unknown fields, malformed types, duplicate documents, invalid decisions, and
  verifier failures become `uncertain` and produce no substantive draft.
- Prompt-injection detection runs before evidence verification.
- Every result, including `supported`, still requires human approval.

`FailClosedEvidenceVerifier` is the default. It always returns `uncertain`, so
deployments cannot silently produce answers before a real model adapter is
configured and evaluated. `StructuredEvidenceVerifier` is the provider-neutral
boundary for a model adapter. The adapter receives the question and retrieved
candidates and must return the structure above.

`OpenAIEvidenceVerifier` is the optional hosted adapter. It uses the Responses
API with strict JSON Schema output, disables response storage, requires an
explicit deployment model, and applies the same local validation after the API
returns. Enable it with `SUPPORT_COPILOT_EVIDENCE_VERIFIER=openai`,
`SUPPORT_COPILOT_OPENAI_MODEL`, and `OPENAI_API_KEY`. A partial or unknown
configuration stops application startup rather than silently changing modes.

`GroqEvidenceVerifier` is the free-tier development adapter. It uses Groq Chat
Completions with `strict: true` JSON Schema output and defaults to
`openai/gpt-oss-20b`. Enable it with
`SUPPORT_COPILOT_EVIDENCE_VERIFIER=groq` and `GROQ_API_KEY`; optionally override
the model with `SUPPORT_COPILOT_GROQ_MODEL`. Groq currently documents strict
mode only for selected models, so model changes must be checked before use.

- Groq structured outputs: https://console.groq.com/docs/structured-outputs
- Groq rate limits: https://console.groq.com/docs/rate-limits
- Groq data controls: https://console.groq.com/docs/your-data

Questions and retrieved passages may contain customer or operational data.
Before enabling a hosted verifier, define redaction, retention, regional,
access-control, and incident-response requirements for the deployment. Never
put secrets into ticket text or documentation passages.

Verifier candidates must be tuned only on development data. Report supported
precision, supported recall, and unsupported abstention separately, then freeze
the candidate before evaluating validation. The locked test remains unavailable
during development.

## Resumable hosted evaluation

Hosted development evaluation writes an atomic checkpoint after each completed
case. Resume a Groq run after its quota window resets with the same command and
the `--resume` flag. The evaluator rejects reuse if the provider, model,
verifier contract, prompt, schema, development data, corpus, case selection, or
retrieved candidate inputs changed. This prevents a single reported result from
silently mixing configurations.

```bash
PYTHONPATH=src python scripts/evaluate_groq_evidence.py \
  --output artifacts/groq_evidence_development.json

PYTHONPATH=src python scripts/evaluate_groq_evidence.py \
  --output artifacts/groq_evidence_development.json --resume
```

This protects evaluation progress; it does not increase provider capacity or
make a free-tier API suitable for production traffic.

Development retrieval reports candidate recall separately from gated recall.
Candidate recall answers whether the correct document reached the evidence
verifier; gated recall additionally applies the lexical confidence threshold.
Keeping these metrics separate prevents a conservative pre-verifier gate from
being misdiagnosed as a ranking failure.

The Medusa development-only calibration exhaustively checks every decision
boundary induced by the observed top score and top-two score ratio. No member
of that threshold family can simultaneously retain at least 80% supported
Recall@3 and abstain on at least 80% of unsupported cases. The best threshold
that retains 6/7 retrievable supported cases abstains on only 19/88 unsupported
cases; the best threshold meeting 80% unsupported abstention retains only 2/7
supported cases. Therefore runtime defaults remain unchanged and another Groq
run is deferred until the gate uses a more informative signal. Reproduce the
diagnostic with:

```bash
PYTHONPATH=src python scripts/calibrate_medusa_retrieval_confidence.py
```

The frozen output is in
`artifacts/medusa_confidence_gate_calibration.json`. It records protected-split
checksums but does not evaluate validation or the locked test.

A subsequent zero-cost candidate measures alignment against individual evidence
sentences rather than whole passages. It combines title-term coverage with
IDF-weighted full-question coverage and contains no case IDs or product-specific
rules. At the development Recall@3 requirement it improves unsupported
abstention from 21.6% for the best score/ratio boundary to 64.8%, but still
misses the 80% requirement. `sentence_evidence_alignment_v1` is therefore
recorded as rejected and is not wired into runtime behavior:

```bash
PYTHONPATH=src python scripts/evaluate_medusa_evidence_alignment.py
```

Its frozen result is
`artifacts/medusa_evidence_alignment_candidate.json`. No hosted-model call or
protected-split evaluation was used.

## Pinned local semantic gate candidate

`local_semantic_alignment_v1` adds cosine similarity from the pinned
`all-MiniLM-L6-v2` revision to the two sentence-alignment signals. It runs with
`local_files_only=True`, uses no hosted API, and contains no case-specific
rules. On the repaired development split its selected boundary reaches 6/7
supported Recall@3 (85.7%) and 71/88 unsupported abstention (80.7%). This passes
the development point targets, but the 95% lower bounds are only 48.7% and
71.2%, respectively. It was selected for independent validation, but that
Medusa-only validation path is now paused and remains outside production.

```bash
pip install -e '.[semantic]'
HF_HUB_OFFLINE=1 PYTHONPATH=src \
  python scripts/evaluate_medusa_local_semantic_gate.py
```

The local arm64 diagnostic measured 52.2 ms mean and 64.3 ms p95 warm encoding
latency for one question plus three passages. The full evaluation process
peaked at 848,936,960 bytes of resident memory, above the current Render free
instance's 512 MB limit. This is not a cross-environment capacity benchmark,
but it blocks deployment until a production-container memory profile passes.
Runtime behavior remains unchanged. See
`artifacts/medusa_local_semantic_gate.json` and
`artifacts/medusa_local_semantic_gate_resource_profile.json`.

## Rejected local verifier candidate

A pinned TinyRoBERTa SQuAD2 extractive model was tested only on the development
split as a zero-cost deployment candidate. Quantized ONNX reduced the model to
about 78 MB and local peak memory to about 223 MB, but evidence scores overlapped
too heavily between supported and unsupported cases. At a conservative
threshold it recovered only about 1 of 13 supported development cases. The
candidate was rejected before validation or locked-test evaluation; it is not
part of the application or deployment image.
