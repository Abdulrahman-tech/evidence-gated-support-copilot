# Support Copilot MVP

This first vertical slice proves three behaviors before adding a UI or paid
model dependency:

1. support policies are split and indexed locally;
2. a ticket retrieves evidence and produces a cited draft;
3. retrieval quality is measurable and suspicious instructions trigger review.

All drafts require human review. This is intentional: the MVP assists an agent
but does not have authority to contact a customer.

## Try it in Python

```python
from support_copilot import KnowledgeBase, KnowledgeDocument, SupportCopilot

documents = [
    KnowledgeDocument(
        document_id="refunds",
        title="Refund policy",
        text="Customers may request a refund within 30 days of purchase.",
        source="handbook/refunds",
    )
]
copilot = SupportCopilot(KnowledgeBase(documents))
draft = copilot.draft("Can I get a refund after 20 days?")

print(draft.answer)
print([citation.source for citation in draft.citations])
print(draft.needs_human_review)
```

## Measure the baseline

The checked-in corpus contains 50 synthetic policies and 500 cases split into
300 development, 100 validation, and 100 locked test cases. From the repository
root, run:

```bash
PYTHONPATH=src python scripts/evaluate_support_copilot.py
```

The default report evaluates validation only. It prints retrieval recall at 1
and 3 plus unsupported-question abstention. Do not run against `--split test`
while tuning. The test checksum is recorded in `data/dataset_manifest.json`,
and the manifest marks those labels as synthetic and unreviewed.

## Review the locked test set

Open `review/test_review.xlsx` and filter `review_scope` to `manual_required`.
Compare those 40 customer messages with the knowledge reference, correct any
bad label, choose `approved`, and add a note when useful. Do not expose model
predictions during this process.

Eighty rows contain minimally redacted language from real customer-care
conversations. Preserve spelling, slang, and grammar unless redaction left the
message unintelligible; that natural variation is part of the benchmark. The
other twenty rows are explicitly labelled human-authored safety cases.

The other 60 real cases are marked `automated_checks_only` and `auto_checked`.
That means they passed duplicate, schema, redaction, and source-integrity
checks; it does not claim individual human approval. Do not change their scope
or status.

When all 40 manual rows are approved, export the `Test Review` sheet as CSV and
validate it without changing the test set:

```bash
PYTHONPATH=src python scripts/import_test_review.py review/completed_test_review.csv
```

Only after validation succeeds, intentionally apply and relock it:

```bash
PYTHONPATH=src python scripts/import_test_review.py \
  review/completed_test_review.csv --apply
```

## Next increments

- persist documents and tickets in PostgreSQL with pgvector;
- add an LLM generator that accepts only retrieved evidence;
- expose ingestion and drafting through a FastAPI service;
- optionally complete individual human review of the remaining 60 real cases;
- add groundedness, citation correctness, latency, and cost measurements;
- add an agent-review UI and record accept/edit/reject feedback.
