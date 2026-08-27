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
