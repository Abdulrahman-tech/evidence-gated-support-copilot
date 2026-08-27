# Building an evidence-gated support copilot for developer-tool companies

## The short version

I built an authenticated support copilot whose first reference implementation
answers Kubernetes-core questions from a pinned copy of the official
documentation, returns exact citations, and
abstains when the evidence, scope, or verifier is unsafe. The interesting part
is not the chat interface. It is the control system around it: tenant isolation,
scope routing, retrieval-confidence gates, prompt-injection checks, evidence
validation, observable trajectories, and a release process that refuses to turn
small or self-reviewed datasets into production claims.

The current result is a portfolio-ready local product, not a claimed production
deployment. It runs without paid model APIs and has 77 automated tests. Its
production evaluation gate remains closed until an independently reviewed
Kubernetes benchmark exists.

## The problem

Developer-support answers often sound plausible while silently mixing versions,
vendors, and adjacent tools. A Kubernetes-tagged question may actually depend
on Helm, Argo CD, a cloud provider, an ingress controller, or application-specific
behavior. A generic retrieval-augmented chatbot can retrieve a related page and
still invent the relationship that matters.

I therefore defined the product narrowly: draft read-only answers for Kubernetes
core, using only approved official evidence. The copilot must prefer an explicit
“I cannot answer this from the pinned corpus” over an attractive unsupported
answer. Every result remains subject to human review.

## Architecture

The runtime follows five observable stages:

1. **Scope:** deterministically route ecosystem-specific questions before paid
   verification or retrieval can create false confidence.
2. **Retrieval:** search only the authenticated tenant's pinned corpus and apply
   absolute-score and top-result separation gates.
3. **Safety:** treat both the ticket and retrieved passages as untrusted input;
   block known prompt-injection language.
4. **Evidence:** require a structured supported, unsupported, or uncertain
   decision. Every supported claim must name a retrieved document and copy an
   exact contiguous quote from its passage.
5. **Response:** return cited evidence or abstain. No path sends a message or
   changes a cluster.

Each response includes a content-free trajectory such as:

```text
scope:kubernetes_core
retrieval:confident
safety:passed
evidence:supported
response:cited
```

The trace contains no ticket text, passage text, credentials, or provider error
details. It makes control-flow regressions testable and gives operators a useful
aggregate signal: where is the product abstaining, routing, or failing?

## Corpus and provenance

The corpus contains 7,341 sections from 1,460 English Kubernetes documentation
pages, pinned to `kubernetes/website` commit
`25f3dcbed7429ebe20174ccc7000428d0f0aedda`. Every section retains a stable
document ID, repository path, commit, product area, and official source URL.

Pinning matters. It makes an evaluation reproducible and prevents a changing
website from silently altering the evidence behind an answer. It also exposes a
real product decision: when the corpus is upgraded, the benchmark must be checked
for outdated or moved evidence before promotion.

## Trajectory regression testing

The dedicated trajectory suite blocks seven high-risk regressions:

- a supported answer must traverse confident retrieval and validated evidence;
- low-confidence retrieval must skip the verifier and return no citation;
- explicit adjacent-tool questions must route and abstain before verification;
- prompt injection in a ticket must never reach the verifier;
- prompt injection in retrieved content must never reach the verifier;
- a temporary verifier outage must abstain without logging provider details;
- a fabricated or non-contiguous evidence quote must fail validation and abstain.

The complete project currently runs 77 tests. GitHub Actions executes the suite
on Python 3.10 and 3.12, builds the Docker image, and verifies that the image has
a healthcheck and runs as a non-root user. A separately triggered release job
opens the locked evaluation only after the product settings are frozen.

## Authentication and deployment boundary

The local demo accepts a development key from the environment. The deployment
path is different: it generates a high-entropy bearer key once, stores only its
SHA-256 digest in a read-only mounted secret, hashes incoming credentials, and
uses constant-time digest comparison. Multiple digests allow key rotation
without downtime. Raw production keys do not belong in the server environment,
image, repository, ticket, or logs.

This is only the application half of deployment security. TLS termination,
gateway rate limits, workload identity, secret-manager audit logs, observability,
load testing, scanning, rollback, and incident response remain environment-level
release requirements.

## What the data work taught me

An authentic Stack Overflow source-yield pilot showed that many questions tagged
Kubernetes are actually ecosystem or vendor questions. A bounded historical
scan then examined 892 accepted-answer questions without redistributing answer
bodies or using a hosted model. It found 103 answers with explicit official
Kubernetes documentation links; 90 mapped to pages in the pinned corpus.

That is useful provenance, but it is not ground truth. An external link can point
to a relevant page without identifying the exact section that answers the core
question. Those records remain audit candidates and are excluded from production
metrics until a human confirms the exact evidence.

This finding changed the project plan. Continuing to collect larger datasets
would produce more review work but not a better product demonstration. I paused
expansion and moved the strongest research controls into the shipped vertical
slice.

## Mistakes caught by the process

Two corrections materially improved the project:

- The first production-readiness script measured the older Medusa experiment,
  not the Kubernetes product. I replaced it with a Kubernetes-specific,
  fail-closed release contract rather than presenting irrelevant metrics.
- Early collection caches used page numbers without hashing the complete query.
  Different date windows could therefore reuse a valid response from the wrong
  request. Cache keys now include request or answer-ID digests, and the unreviewed
  pool was rebuilt before its yield was trusted.

These are exactly the failures a case study should include. They demonstrate why
provenance, split isolation, and reproducible tooling matter more than a polished
accuracy number.

## Current status and next proof

The product is ready for portfolio demonstrations and developer interviews. It
is not yet ready for unsupervised customer traffic. The next meaningful proof is
not another large scrape. It is feedback from developer-tool support teams on
three questions:

1. Is evidence-bound drafting painful enough to matter in their workflow?
2. Are routing and abstention more valuable than broad but unreliable coverage?
3. Which integration boundary—ticketing, docs search, or internal support
   console—would make a pilot easiest?

If those conversations show demand, the next investment is an independently
reviewed benchmark and a deployment behind a real gateway. If they do not, the
project still demonstrates production-minded AI engineering: controlled scope,
measurable trajectories, safe failure, reproducible evidence, and honest gates.

## Run the demonstration

The project includes a non-root Docker image and a zero-cost local verifier. See
[the portfolio demo runbook](portfolio_demo.md) for the exact command and three
expected flows: cited Kubernetes answer, routed Helm abstention, and unrelated
question abstention.
