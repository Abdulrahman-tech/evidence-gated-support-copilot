# Medusa independent-validation issue pilot

> **Paused:** Do not review this packet while Kubernetes core is the primary
> product track. It is preserved only so the Medusa experiment remains
> reproducible if it is intentionally resumed later.

Review all 30 rows in `review_packet.json` using only the linked GitHub issue and
the pinned official Medusa documentation. Do not open the semantic calibration
artifact, run the evaluator, or consult earlier benchmark labels while deciding.

For every row:

1. Open `source_url` and read the complete issue, not only its title.
2. Set `reviewer_decision` to `supported` only when one official corpus section
   directly answers the core question. Set `expected_document_id` to that exact
   section ID.
3. Use `unsupported` when the issue is genuine but the pinned official corpus
   does not directly answer it. Leave `expected_document_id` empty.
4. Use `ambiguous` when the issue lacks enough context for a reliable decision,
   or `outdated` when it depends on an obsolete version or architecture. Leave
   `expected_document_id` empty.
5. Set `review_status` to `approved` only after completing the decision.

After all rows are reviewed, complete `reviewer_attestation.json`. The reviewer
ID can be a name or stable alias; `completed_at` should be an ISO 8601 timestamp.
Keep `reviewed_without_model_or_retriever_outputs` false unless the blind rule
was genuinely followed.

The evaluator intentionally fails until the packet and attestation are complete:

```bash
PYTHONPATH=src python scripts/evaluate_medusa_independent_validation_pilot.py
```

This issue-only pilot measures source yield and unsupported abstention. It is
not the full production qualification set and it does not open the locked test.
