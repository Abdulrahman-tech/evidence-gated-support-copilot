# Kubernetes benchmark recovery audit

This is a 20-case blind audit of the benchmark source-selection method. It is
not a development, validation, challenge, or locked-test split, and its cases
must remain excluded from all later evaluation sets.

For each row, open the Stack Overflow source page and compare the core question
with the pinned official Kubernetes corpus. Choose `supported` only when one
official section directly answers it, and record that section's `document_id`.
Choose `unsupported` when no pinned official section directly answers it and
leave the document ID blank. Use `ambiguous` when the source lacks enough
context and `outdated` when it depends on an obsolete Kubernetes version or
architecture. Set `review_status` to `approved` only after checking the source
and evidence.

The review packet intentionally omits accepted-answer links, selection strata,
retriever output, model predictions, suggested labels, and confidence scores.
The review workbook is generated into the ignored `outputs/` directory so human
decisions are not accidentally committed before validation.
