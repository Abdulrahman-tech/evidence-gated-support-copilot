# Evidence-Gated Support Copilot for Developer-Tool Companies

A production-minded beta for drafting developer-support responses from approved
documentation. The Kubernetes-core track is the first reference implementation:
it retrieves pinned official passages, checks direct evidence, cites its sources,
flags suspicious instructions, and abstains when support is insufficient.

[**Live demo**](https://evidence-gated-support-copilot.onrender.com) ·
[**Release status**](docs/release_status.md) ·
[**Operations guide**](docs/operations.md) ·
[**Technical case study**](docs/technical_case_study.md) ·
[**Quality gate**](https://github.com/Abdulrahman-tech/evidence-gated-support-copilot/actions/workflows/quality.yml)

> **Current status:** production-minded portfolio beta, not production ready.
> The public demo uses an explicitly non-production lexical evidence verifier,
> every response requires human review, and the Kubernetes independent release
> benchmark is not yet complete.

## What it does

```text
Support question
    → tenant and scope checks
    → retrieval from pinned official documentation
    → prompt-injection screening
    → direct-evidence verification
    → cited draft or abstention
    → mandatory human review
```

The system does not send customer messages or make infrastructure changes. Its
core product decision is whether available evidence is strong enough to support
a reviewable draft.

## Current proof

| Area | Verified today | Honest boundary |
|---|---|---|
| Runtime | FastAPI service, authenticated tenant boundary, non-root Docker image | Public demo key is demonstration access, not production authentication |
| Evidence | Exact document IDs, quotes, source URLs, and fail-closed verifier contract | Hosted demo uses deterministic lexical overlap, not a qualified semantic verifier |
| Safety | Injection tests, input limits, application rate limiting, security headers, dependency audit, and secret scan | A shared gateway limiter and production security monitoring remain open |
| Evaluation | Frozen splits, leakage groups, Wilson intervals, trajectory regressions | Kubernetes independent development, validation, and locked-test gates have not passed |
| Delivery | Public HTTPS demo, structured request logs, external smoke monitor, bounded failure injection and load checks, release-drift detection, and GitHub quality gates | Render free tier and six-hour monitoring provide no production SLA |

The historical mixed-support benchmark remains useful as engineering evidence,
but it is not a Kubernetes production claim:

| Historical split | Supported | Unsupported | Recall@1 | Recall@3 | Unsupported abstention |
|---|---:|---:|---:|---:|---:|
| Development | 80 | 20 | 75.0% | 78.8% | 70.0% |
| Validation | 80 | 20 | 66.2% | 68.8% | 85.0% |
| Challenge diagnostic | 80 | 100 | 55.0% | 56.2% | 73.0% |

The challenge labels were not independently adjudicated case by case, so that
row is diagnostic only. See the [release status](docs/release_status.md) for the
open gates and the exact claim boundary.

Read the [technical case study](docs/technical_case_study.md) for the product
architecture, trajectory evaluation, safety decisions, measured results, and
honest release boundary.

<details>
<summary><strong>Research history, corpus work, and experiment log</strong></summary>

The sections below preserve failed experiments, dataset audits, candidate
comparisons, and provenance. They are retained for reproducibility and are not
the shortest path to understanding the current product.

## Kubernetes evidence-first track

The Kubernetes track targets evidence-bound technical-support drafting, not
autonomous cluster changes. Its official corpus is pinned to Kubernetes website
commit `25f3dcbed7429ebe20174ccc7000428d0f0aedda` and contains 7,341 unique
sections from 1,460 English documentation pages. Each section retains its
document ID, source path, commit, product area, and official source URL.

The first qualification artifact is a 60-case source-yield pilot built from
authentic 2025–2026 Stack Overflow Kubernetes questions. It is deliberately
excluded from development, validation, challenge, and locked-test metrics. The
visible review packet contains no retriever result, suggested document, AI
label, or screening stratum. Review it manually in two batches of 30 against
the pinned official corpus. This pilot used no hosted-model calls and does not
yet support a production-readiness claim.

```bash
PYTHONPATH=src python scripts/build_kubernetes_corpus.py \
  --source /path/to/kubernetes-website \
  --commit 25f3dcbed7429ebe20174ccc7000428d0f0aedda

PYTHONPATH=src python scripts/collect_kubernetes_questions.py
PYTHONPATH=src python scripts/build_kubernetes_source_yield_pilot.py
```

See [the Kubernetes scope](docs/kubernetes_scope.md) for the release boundary,
licensing, attribution, and planned qualification gates.

The first adjacent-corpus candidate is the official Helm 3.19 documentation,
pinned and built as a physically separate `helm-v3` corpus. It contains 712
unique sections from 126 pages and is intentionally not enabled for runtime
routing until version-specific retrieval and evidence gates pass. See
[the Helm scope](docs/helm_scope.md) for provenance and qualification status.

## Medusa production track

The production-focused track is scoped to technical support for merchants and
developers operating Medusa commerce stores. It uses a single `medusa` tenant
and official documentation for authentication, customers, fulfillment,
inventory, orders, payments, and products. The existing mixed-company Twitter
data is retained only as a legacy stress test.

The initial pinned corpus contains 488 unique sections from 85 official Medusa
documentation pages. The expanded candidate corpus contains 3,342 unique
sections from 414 pages across 14 documentation areas. Every section records
its source URL, repository path, commit, product area, and tenant.

Two authentic candidate pools are kept separate from evaluation labels:
120 public issue titles for abstention research and 100 answered GitHub
Discussion Q&A titles for building a balanced, tenant-specific benchmark. The
Discussion candidates include retriever suggestions for review, but none is a
trusted label until a reviewer verifies it against official documentation.

```bash
PYTHONPATH=src python scripts/build_medusa_corpus.py \
  --source /path/to/medusa \
  --commit c4a823a19e4787bb69f2c3238a3cb5cb0918d7cc

PYTHONPATH=src python scripts/collect_medusa_discussions.py
PYTHONPATH=src python scripts/build_medusa_expanded_corpus.py \
  --source /path/to/medusa \
  --commit c4a823a19e4787bb69f2c3238a3cb5cb0918d7cc
PYTHONPATH=src python scripts/build_medusa_discussion_candidates.py
```

Review the resulting mappings in
`review/medusa_discussion_review.xlsx`, starting with the 47 high-priority
rows. The workbook contains the original source URLs, accepted-answer URLs,
the top three official-document candidates, and a complete knowledge reference.

The owner-authorized AI-assisted review approved all 100 rows: 30 supported,
40 unsupported, 28 outdated, and 2 ambiguous. Outdated and ambiguous rows are
excluded. The development and validation splits retain those AI-assisted labels.
The original 14 locked-test candidates were then reviewed independently in a
blind manual-review workbook. That review retained 11 usable cases (10 supported
and 1 unsupported) and excluded 2 ambiguous and 1 outdated case. The locked test
is independent, but remains too small and imbalanced for a production claim.

A separate expansion pool contains 1,500 authentic public Medusa issue reports.
It excludes every previously reviewed Discussion source, carries source URLs,
timestamps, labels, body hashes, product-area tags, and leakage-group IDs, and
contains no evaluation labels or retriever predictions. This pool is input to
the next adjudication cycle; it is not itself a benchmark.

Before adjudication, whole leakage groups were deterministically assigned to
521 development candidates, 388 blind-validation candidates, 408 blind
locked-test candidates, and 183 reserves. The assignment manifest locks these
roles before labels are known and prevents related questions from crossing
roles.

The development-only workbook at `review/medusa_development_review.xlsx`
contains AI-assisted top-three evidence suggestions for all 521 development
cases and the complete pinned knowledge reference. High-precision automation
marked 27 cases supported and 116 unsupported; the other 378 are deferred and
must not be treated as labels. The frozen 30-case quality audit (15 supported,
15 unsupported) is in `review/medusa_development_quality_audit.xlsx`. The 143
proposed decisions failed that audit: the owner marked 11 correct, 11
incorrect, and 8 uncertain. None of the 143 proposals was imported.

The fail-closed `development_direct_answer_v2` experiment removes automatic
unsupported labels because retrieval failure does not prove that documentation
is absent. It also rejects defect-like questions and accepts only direct,
non-defect instructional requests with strong area-aligned evidence. This left
one pending candidate and 520 deferred cases; the one candidate was already in
the first audit, so no honest unseen audit sample can yet be formed. The v2
manifest explicitly sets `import_allowed` to false. More reviewed development
examples are required before attempting another automation rule.

The next development review is limited to 30 unseen cases in
`review/medusa_development_manual_batch_02.xlsx`. It contains 10 cases from
each of three rule-learning cohorts, spans 13 product areas, and uses 30
distinct leakage groups. Reviewers choose supported, unsupported, outdated,
or ambiguous; supported rows require an official document ID. This is a
development batch with visible retrieval evidence, not a blind evaluation.

Batch 02 added 30 approved development labels: 1 supported and 29 unsupported.
Batch 03 reviewed another 30 cases and imported 28 usable labels: 2 supported
and 26 unsupported. Its two ambiguous decisions remain in the batch exclusion
record and are not benchmark labels. Development now contains 100 cases (21
supported and 79 unsupported). Validation and locked test remain untouched.

The two V1 high-confidence cases in Batch 03 were not clean supported matches
(one was ambiguous and one unsupported), while two explicit-issue cases had
direct supporting documentation. This result is retained as evidence against
promoting the current automation confidence rule without further validation.

Automation provenance is stored under
`data/medusa/development_automation`. No validation or locked-test source was
included or modified by this workflow.

```bash
PYTHONPATH=src python scripts/validate_medusa_large_candidate_pool.py \
  --sources data/medusa/candidate_pool/sources.json \
  --manifest data/medusa/candidate_pool/manifest.json
```

```bash
PYTHONPATH=src python scripts/build_medusa_benchmark_splits.py
```

Evaluate only the Medusa development and validation splits while keeping the
locked test unavailable:

```bash
PYTHONPATH=src python scripts/evaluate_medusa_benchmark.py --split all
```

The current `bm25_title_dedup_v2` candidate indexes section titles twice and
returns unique documents rather than duplicate passages. On development it
improved gated Recall@3 from 9.5% to 23.8%. On validation, Recall@1 and Recall@3
remained 16.7%, while unsupported-question abstention improved from 37.5% to
62.5%. The 14-case validation interval remains wide, and accepted-result risk
is still too high for autonomous answers. The service therefore retains
mandatory human review; the locked test has not been evaluated.

See [the Medusa scope](docs/medusa_scope.md) for supported areas, provenance,
and the release boundary.

## Dataset and current validation baseline

- 50 synthetic support policies
- 300 development, 100 validation, and 100 locked test cases
- Validation Recall@1 and Recall@3 are reported by the evaluation command
- The test split is checksummed and remains unevaluated until human review
- No API key, network access, or model cost required

The generated cases validate the evaluation workflow, not production quality.
The manifest labels the test set `synthetic_unreviewed`; its results must not be
presented as a final benchmark until a person reviews all 100 test labels.

The separate real-world benchmark contains 80 minimally redacted customer messages
from TweetSumm and 20 human-authored safety cases. The source messages originate
from the Customer Support on Twitter corpus. The repository records source
conversation and tweet IDs but does not redistribute either complete source
dataset. This benchmark is for non-commercial portfolio and research use under
the recorded CDLA-Sharing-1.0 and CC-BY-NC-SA-4.0 terms.

Its fast-review workflow requires manual review of all 20 safety cases and a
deterministic sample of 20 real messages. The other 60 real messages receive
structural checks only and remain explicitly labelled `auto_checked`.

## Reviewed real-world baseline

The checksum-verified real benchmark was evaluated once after review. With the
original score threshold of 5.0, the local lexical retriever achieved Recall@1
of 68.8%, Recall@3 of 76.2%, and unsupported-question abstention of 25.0%.
These are baseline results: the low abstention rate shows that confidence
calibration and out-of-domain rejection need improvement before this system is
suitable for production.

The original result is preserved in
`data/real_benchmark/evaluation_results.json`. The command below evaluates the
current candidate, so it should only be used at a deliberately frozen test
milestone:

```bash
PYTHONPATH=src python scripts/evaluate_support_copilot.py --benchmark real --split test
```

## Post-baseline retrieval and confidence calibration

The first lexical calibration achieved perfect results on synthetic data but
collapsed on a new real-world validation split. That exposed benchmark
overfitting: real validation Recall@1 was 65.0%, Recall@3 was 70.0%, and
unsupported abstention was 0%.

The current `bm25_v1` candidate uses BM25 length normalization plus a confidence
gate requiring a score of at least 9.0 and a top-to-second score ratio of at
least 1.1. On the current checksummed benchmark it achieves development
Recall@1 of 75.0%, Recall@3 of 78.8%, and unsupported abstention of 70.0%.
Validation is lower at 66.2%, 68.8%, and 85.0%, respectively. Low-confidence
retrievals produce the no-evidence response with no citations instead of
drafting from weak evidence.

A development-only sweep selected a score of 10.0 with a ratio of 1.0. The
candidate preserved development recall and raised development abstention to
75.0%, but independent validation Recall@3 fell to 67.5% and the
development-validation gap widened. The candidate was rejected, the 9.0/1.1
runtime gate was retained, and the locked test was not evaluated. The
calibration and rejection evidence are stored separately so a development win
cannot silently become a production default.

Real development, validation, and test contain no overlapping source
conversations. Development and validation each contain 80 supported messages
and 20 genuine messages whose exact resolution is absent from that split's
knowledge corpus.

## Adjudicated challenge set

The separate real challenge set contains 80 supported messages and 100 genuine
messages proposed as unsupported. It shares no source conversations with
development, validation, or the locked test. Its unsupported labels are not
trusted automatically: a reviewer compares each question with the retriever's
top three candidate documents and chooses `unsupported`, `answerable`, or
`ambiguous`. Ambiguous cases are excluded from the judged set.

Open `review/challenge_unsupported_review.xlsx` and filter
`review_priority` to `high` first. Those 22 cases are the ones the current
confidence gate would accept and therefore carry the most immediate risk. When
all rows are approved, export the `Unsupported Review` sheet as CSV and run:

```bash
PYTHONPATH=src python scripts/import_challenge_review.py --review <review.csv> --apply
PYTHONPATH=src python scripts/evaluate_support_copilot.py --benchmark real --split challenge
```

The evaluator refuses to score the challenge until adjudication is complete.
The raw challenge file remains unchanged; import creates a separate checksummed
`challenge_judged.json`. Retriever predictions are visible during this review,
so the resulting split is an adversarial development challenge rather than an
independent final test.

If the owner deliberately accepts every proposed unsupported label without
case-by-case review, import with `--review-method blanket_approval`. The manifest
records `user_blanket_approved`, and evaluation prints a warning so those
results cannot be confused with human-adjudicated labels.

Evaluation reports Recall@1, Recall@3, unsupported abstention, 95% Wilson
confidence intervals, and a selective risk/coverage curve across score
thresholds. This makes the coverage-versus-error tradeoff explicit instead of
selecting a threshold from a single accuracy number.

The locked real test was not rerun during this tuning. Its original result
remains the honest baseline until a new evaluation milestone is frozen. The
remaining recall gap is evidence that lexical retrieval still underfits
semantic paraphrases; hybrid embedding retrieval is the next candidate.

## Hybrid semantic experiment

`hybrid_rrf_v1` combines BM25 and local `all-MiniLM-L6-v2` semantic rankings
with reciprocal rank fusion while retaining the existing BM25 confidence gate.
This isolates ranking improvements from abstention-policy changes and runs
offline when the optional model is already cached.

On validation, the hybrid candidate improved Recall@1 from 67.5% to 68.8% and
Recall@3 from 68.8% to 71.3% while preserving 90.0% unsupported abstention. On
the harder challenge, Recall@3 improved from 55.0% to 58.8%, but Recall@1 fell
from 55.0% to 53.8%; challenge abstention remained 78.0%. Because the challenge
labels were blanket-approved and the top-rank result regressed, this candidate
is retained as an experiment rather than promoted over `bm25_v1`. The locked
final test remains untouched.

`hybrid_rrf_v2` reduces semantic influence and uses rank constant 0 with a
semantic weight of 0.75. It changes only four development top results. Compared
with the lexical baseline, validation Recall@1 improves from 66.2% to 67.5% and
Recall@3 improves from 68.8% to 71.3%, while unsupported abstention remains
85.0%. On the challenge diagnostic overlay, Recall@1 improves from 62.0% to
63.4% and Recall@3 from 63.4% to 66.2%, with abstention unchanged at 73.3%.

The v2 candidate is not a production default: confidence intervals overlap,
development-validation gaps remain above five points, and the production image
does not yet package the embedding model. A fresh independent validation cohort
and container-level model packaging checks are required before promotion. The
locked test remains untouched.

```bash
pip install -e '.[semantic]'
HF_HUB_OFFLINE=1 PYTHONPATH=src python scripts/evaluate_hybrid_candidate.py --candidate v2 --split development
```

</details>

## Quick start

Python 3.10 or newer is required.

```bash
python scripts/build_dataset.py
PYTHONPATH=src python scripts/evaluate_support_copilot.py
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Run the authenticated API

The API fails closed unless both the knowledge path and an API-key-to-tenant
mapping are supplied. Ticket text is not written to the structured audit log.

```bash
export SUPPORT_COPILOT_KNOWLEDGE_PATH=data/kubernetes/knowledge.json
export SUPPORT_COPILOT_API_KEYS='{"replace-with-a-secret":"kubernetes"}'
uvicorn support_copilot.api:create_app_from_env --factory --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` for the authenticated review interface. The
default command remains fail-closed. For a zero-cost portfolio demonstration,
enable the explicitly non-production local verifier and the documented demo
threshold:

```bash
export SUPPORT_COPILOT_EVIDENCE_VERIFIER=local_demo
export SUPPORT_COPILOT_MINIMUM_SCORE_RATIO=1.0
```

See [the local portfolio demo runbook](docs/portfolio_demo.md) for expected
supported, routed, and abstained flows and the equivalent Docker command.

## Deploy the portfolio demo

[**Open the live demo**](https://evidence-gated-support-copilot.onrender.com)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Abdulrahman-tech/evidence-gated-support-copilot)

The included `render.yaml` deploys the Docker image on Render's free web-service
plan, waits for GitHub checks before redeploying, and monitors `/healthz`. Enter
`local-demo-key` in the interface. This is deliberately public demonstration
access, not a production credential.

The hosted demo uses the explicitly non-production `local_demo` verifier and
retains mandatory human review. Render's free service sleeps after 15 minutes
without traffic and can take about a minute to wake. It is a portfolio endpoint,
not evidence that the independent production-readiness gates have passed.

Runtime controls, metrics, dependency locks, security scans, and their honest
deployment boundaries are documented in the [operations guide](docs/operations.md).

The command above runs in `fail_closed` verification mode. For the free-tier
development path, install and configure the Groq adapter. It defaults to
`openai/gpt-oss-20b`, which supports Groq strict structured output:

```bash
pip install -e '.[groq]'
export SUPPORT_COPILOT_EVIDENCE_VERIFIER=groq
export GROQ_API_KEY='set-this-locally'
# Optional override:
export SUPPORT_COPILOT_GROQ_MODEL='openai/gpt-oss-20b'
```

Smoke-test the adapter on five development cases, then run the complete
development split and save its predictions:

```bash
PYTHONPATH=src python scripts/evaluate_groq_evidence.py --max-cases 5
PYTHONPATH=src python scripts/evaluate_groq_evidence.py \
  --output artifacts/groq_evidence_development.json
```

The hosted-verifier evaluation sends the same top three passages used by the
production API. This avoids evaluation-serving skew and reduces dynamic input
compared with the earlier five-passage evaluator. Run retrieval evaluation
offline first; do not spend hosted-model quota on a retrieval candidate that
has not passed its independent retrieval gates.

This command intentionally has no validation or locked-test option. Freeze the
prompt, model, retrieval settings, and acceptance criteria before creating a
separate validation run.

Do not commit the API key or place it in the image. The adapter treats tickets
and documents as untrusted data and fails closed on incomplete output,
timeouts, invalid JSON, or contract violations. Free-tier rate limits make this
suitable for development evaluation, not a production capacity guarantee.

The optional OpenAI adapter remains available through the `openai` extra and
`SUPPORT_COPILOT_EVIDENCE_VERIFIER=openai`.

Request a human-reviewable draft:

```bash
curl -sS http://127.0.0.1:8000/v1/drafts \
  -H 'Authorization: Bearer replace-with-a-secret' \
  -H 'Content-Type: application/json' \
  -d '{"ticket":"Which Kubernetes Service type is reachable only from within the cluster?","limit":3}'
```

Retrieval candidates now pass through the strict contract in
[`docs/evidence_verification.md`](docs/evidence_verification.md). The default
verifier fails closed with `evidence_decision: "uncertain"` and no substantive
draft. A deployment must inject and qualify a structured model adapter before
it can return verified citations; exact evidence quotes and candidate document
IDs are checked again in application code.

`SUPPORT_COPILOT_API_KEYS` is a local-development convenience. A deployment
should mount a digest-only secret file and set
`SUPPORT_COPILOT_API_KEY_HASHES_FILE`; raw bearer keys must remain in the
calling client's secret manager and must never be baked into the image or
server environment. See [deployment secrets](docs/deployment_secrets.md) for
generation, mounting, and rotation instructions.

## Production-readiness gate

Production readiness is fail-closed and is not inferred from a single point
estimate. The gate checks minimum independent sample sizes, case-by-case label
review, tenant isolation, lower bounds of 95% Wilson intervals, and the
development-to-validation generalization gap. It never evaluates the locked
test while tuning.

The complete release contract, including service, security, observability, and
deployment gates, is in [docs/production_readiness.md](docs/production_readiness.md).

```bash
PYTHONPATH=src python scripts/check_kubernetes_production_readiness.py
```

The current Kubernetes candidate intentionally fails closed because its
independent development and validation benchmark has not been completed. The
old Medusa readiness report is retained as historical work but is not evidence
for this Kubernetes product. The locked test is evaluated only once, after the
retriever and thresholds are frozen, by adding `--include-locked-test`.

Read the [MVP guide](docs/mvp.md) for an example and the next planned
increments.

## Project boundaries

The copilot assists a support agent; it does not send customer messages. Every
draft requires human review. A future model-backed generator will consume only
retrieved evidence and will be evaluated for groundedness and citation
correctness before any broader deployment.
