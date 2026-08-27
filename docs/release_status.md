# Release status

## Current classification

**Production-minded portfolio beta — not production ready.**

The public service demonstrates the end-to-end product trajectory with the
pinned Kubernetes corpus. It is suitable for portfolio review, engineering
feedback, and controlled demonstrations. It is not approved for autonomous
customer support or production traffic.

## What is verified

- Kubernetes-core questions are retrieved from a corpus pinned to an official
  Kubernetes website commit.
- Accepted answers retain an exact document ID, evidence quote, and source URL.
- Low-confidence retrieval and unsupported scope produce abstention without a
  citation.
- Ticket text and retrieved passages are treated as untrusted input.
- Prompt-injection, provider-failure, invalid-evidence, routing, and abstention
  trajectories have regression tests.
- The authenticated API enforces tenant selection from the presented key.
- The container runs as a non-root user and exposes health and readiness probes.
- GitHub Actions tests Python 3.10 and 3.12 and verifies the container contract.
- The public Render deployment has passed health, readiness, authentication,
  citation, trajectory, and mandatory-review smoke checks.

## Evaluation boundary

The Kubernetes release benchmark is not complete. Its 60-case authentic source-
yield pilot measures whether pinned Kubernetes documentation can answer sampled
questions, but it is excluded from development, validation, challenge, and
locked-test metrics.

The older mixed-support benchmark is retained as historical engineering
evidence, not as a Kubernetes quality claim:

| Split | Supported | Unsupported | Recall@1 | Recall@3 | Unsupported abstention |
|---|---:|---:|---:|---:|---:|
| Development | 80 | 20 | 0.750 | 0.788 | 0.700 |
| Validation | 80 | 20 | 0.662 | 0.688 | 0.850 |
| Challenge diagnostic | 80 | 100 | 0.550 | 0.562 | 0.730 |

The challenge unsupported labels were blanket-approved rather than independently
adjudicated case by case. They must not be presented as final ground truth.

## Open production gates

Production status remains blocked until all applicable gates in
[`production_readiness.md`](production_readiness.md) pass. The most important
open work is:

1. Complete independently reviewed Kubernetes development and validation sets
   with the required supported and unsupported sample sizes.
2. Freeze retrieval, routing, evidence-verifier, and acceptance settings before
   evaluating a locked test once.
3. Qualify a semantic evidence verifier; the public `local_demo` lexical verifier
   is deliberately non-production.
4. Add gateway rate limiting, dependency locking and scanning, metrics, alerts,
   load tests, rollback verification, and managed secret delivery.
5. Prove reusable onboarding and isolation with a second runtime tenant.
6. Add a review-first support integration without autonomous posting.

## Public demo boundary

The live service is hosted on Render's free tier and uses the documented
`local-demo-key`. That key is public demonstration access, not a security
control. The service may sleep when idle, has no production availability target,
and must not receive confidential support data.

Every response from the current service retains `needs_human_review: true`.
