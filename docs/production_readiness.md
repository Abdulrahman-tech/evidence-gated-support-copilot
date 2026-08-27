# Production readiness contract

The release target is a Kubernetes-core support copilot that drafts answers
only from the pinned official Kubernetes documentation. It never changes a
cluster or sends a customer message, and every response requires human review.
A working endpoint or a high point estimate is not sufficient for release.

## Independent evaluation gates

- Development, validation, and locked-test case IDs do not overlap.
- Every label is produced by an independent human review against the pinned
  corpus; title-based screening and AI suggestions are not ground truth.
- Validation and locked test each contain at least 200 supported and 100
  unsupported cases.
- The lower 95% Wilson bound is at least 0.85 for Recall@1, 0.90 for Recall@3,
  and 0.95 for unsupported-question abstention.
- Development-to-validation Recall@1 and Recall@3 gaps are at most five
  percentage points.
- Exact citation correctness and answer groundedness pass case-by-case human
  review; document-ID retrieval alone is insufficient.
- The locked test is not opened during tuning and is evaluated once after the
  retriever, corpus, router, verifier, and thresholds are frozen.

The 60-case source-yield pilot is excluded from every evaluation split because
it was used to make corpus-scoping decisions. The existing Medusa benchmark is
also excluded because it measures a different product and tenant.

Run the Kubernetes gate during development:

```bash
PYTHONPATH=src python scripts/check_kubernetes_production_readiness.py
```

After all settings are frozen, run the one-time release evaluation:

```bash
PYTHONPATH=src python scripts/check_kubernetes_production_readiness.py \
  --include-locked-test
```

Both commands fail closed when required files, independent-review metadata, or
quality thresholds are missing.

## Safety and isolation gates

- Cross-tenant retrieval is zero in automated adversarial tests.
- Unknown or omitted tenants fail closed.
- Prompt-injection language in tickets or retrieved content produces no
  substantive draft.
- Unsupported, ambiguous, routed, and low-confidence tickets abstain.
- Secrets and raw ticket text are absent from application logs.
- Any hosted verifier's data handling and retention are approved before real
  customer tickets leave the service boundary.

## Deployment gates

- Strong bearer keys are generated randomly; only their SHA-256 digests are
  mounted read-only from a secret manager, following
  [deployment_secrets.md](deployment_secrets.md).
- TLS terminates at a trusted ingress or gateway.
- Gateway and application request limits are enforced.
- Structured logs, metrics, traces, alerts, retention, and deletion procedures
  are configured.
- Load tests meet an agreed latency and concurrency SLO without cross-tenant
  leakage or unsafe fallback behavior.
- Container scanning, dependency scanning, CI, rollback, backup, and incident
  response are exercised before release.

## Current status

The authenticated API, digest-only mounted-secret interface, fail-closed tenant
routing, bounded requests, health/readiness endpoints, structured audit events,
prompt-injection abstention, low-confidence gate, exact evidence contract,
non-root container, and container healthcheck are implemented.

The product is not production-ready yet. The Kubernetes development,
validation, and locked-test benchmark files do not exist, the local overlap
verifier is demo-only, and gateway, observability, load, scanning, rollback,
and incident-response controls have not been exercised. The release checker
reports these absences rather than substituting the old Medusa metrics.
