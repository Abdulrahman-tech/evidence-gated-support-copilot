# Validation and hosted-token strategy

## Decision

Do not manually review the entire 388-case fresh validation packet. All 388
cases are GitHub issue reports. Two independently reviewed issue batches
produced only 3 supported cases from 60 (5.0%; Wilson 95% interval 1.7%-13.7%).
Even the interval's upper bound projects only about 53 supported cases from
388, far below the release gate of 200 supported validation cases.

The 100 previously reviewed answered GitHub Q&A discussions produced 30
supported cases (30.0%; Wilson 95% interval 21.9%-39.6%). This source is better,
but an unfiltered sample would still require roughly 914 candidates at the
conservative lower-bound yield to obtain 200 supported cases.

## Replacement design

Build a stratified benchmark from authentic, source-isolated questions:

1. Supported-candidate stratum: answered Medusa GitHub Q&A whose chosen answer
   links to a page in the pinned official documentation corpus. The answer and
   retriever output may be used only for candidate screening, not as the final
   label.
2. Unsupported-candidate stratum: genuine Medusa issue reports and unanswered
   Q&A that describe behavior not directly covered by the pinned corpus.
3. Remove duplicates and keep leakage groups in exactly one of development,
   validation, locked test, or reserve.
4. Label against the pinned official corpus in a blind manual review. A
   supported label requires a document ID and direct evidence. Accepted answers,
   retriever results, and model labels remain hidden during final adjudication.

## Pilot gate before scaling

Review 30 randomly selected cases from each stratum before collecting or
reviewing hundreds:

- Continue the supported stratum only if at least 26 of 30 are genuinely
  supported. Its Wilson lower 95% bound is then about 70%, making a 300-case
  supported-candidate pool a reasonable target for at least 200 approved
  supported cases.
- Continue the unsupported stratum only if at least 27 of 30 are genuinely
  unsupported or excluded. Otherwise revise its source filter.
- Stop and change the source filter when either pilot gate fails. Do not tune
  retrieval or verifier prompts on these pilot labels if they will later be
  assigned to validation or locked test.

These are source-yield gates, not claims that the final system is 95% accurate.
System quality is established separately with class-specific metrics and 95%
confidence intervals on frozen, independently reviewed data.

## Frozen issue pilot

The development-selected `local_semantic_alignment_v1` thresholds were frozen
before opening a deterministic 30-case sample from the untouched validation
role. The files are under `data/medusa/independent_validation_pilot`. The review
packet deliberately omits product-area strata, retriever output, semantic
features, model predictions, and suggested labels. The evaluator refuses to run
until every decision is approved, supported decisions reference a real corpus
document ID, and a human blind-review attestation is complete.

This is the unsupported/source-yield half of independent validation. It does not
solve the supported-case shortage described below and cannot promote the
candidate to production on its own. The locked test remains unopened.

## Public-source audit result (2026-08-26)

The replacement source filter was tested before a review workbook was created.
The public GitHub Q&A listing exposed 119 answered discussion links. The
collector parsed 118, retained 101 usable unique questions, and found only 16
accepted answers containing a direct official-document URL. All 16 linked
questions were already present in the earlier 100-case review; there were zero
new linked candidates.

The earlier labels also show that a direct official-document link is not a
high-precision supported-case filter: those 16 cases contained 5 supported, 8
unsupported, and 3 outdated decisions. The proposed supported-stratum pilot
therefore fails before adjudication and must not be expanded into a 60-case
workbook.

The public Stack Overflow `medusajs` tag contains only 42 questions, which is
also insufficient for the release sample. The next statistically plausible
source is an authorized export of real Medusa Discord or tenant support
questions. That source requires an explicit data-access, privacy, retention,
and redistribution decision before collection. Without it, the project can be
described as production-engineered but not production-qualified.

## Token order of operations

1. Candidate collection, deduplication, manual labeling, and corpus checks use
   no hosted-model tokens.
2. Retrieval evaluation is fully local. Reject weak candidates before calling
   a hosted verifier.
3. Tune the evidence verifier only on development: first 5 smoke cases, then a
   balanced 20-case diagnostic, then the full frozen development cohort.
4. Freeze model, prompt, corpus checksum, retrieval settings, and gates before
   one validation run. Keep the locked test untouched until release review.
5. The evaluator and production API both send the top three passages. On the
   current development distribution this reduces estimated dynamic input from
   about 753 to 456 tokens per case, or roughly 40%, compared with five
   passages.
6. Save each bounded run to an artifact. On a rate-limit response, wait for the
   provider reset rather than creating keys to circumvent an organization-level
   limit.

Groq's published free limits for `openai/gpt-oss-20b` include 8,000 tokens per
minute and 200,000 tokens per day, but the account limits page is authoritative.
Prompt caching can reduce repeated static-prefix input; cache hits are not
guaranteed. Batch processing is a paid-plan option and is not assumed by this
project.
