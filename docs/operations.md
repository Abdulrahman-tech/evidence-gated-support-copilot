# Operations guide

This guide describes the controls implemented in the portfolio deployment and
the controls still required before real customer traffic is accepted.

## Runtime controls

The API validates the request host, adds defensive browser headers, rejects
oversized tickets, and rate-limits each authenticated API key. Configure the
limiter and trusted hosts with:

```bash
export SUPPORT_COPILOT_RATE_LIMIT_REQUESTS=30
export SUPPORT_COPILOT_RATE_LIMIT_WINDOW_SECONDS=60
export SUPPORT_COPILOT_ALLOWED_HOSTS='support.example.com,127.0.0.1,localhost'
```

The limiter is held in one process. It is useful defense in depth for the demo,
but counters are neither shared across replicas nor durable across restarts. A
production deployment therefore still needs a gateway or shared-store limiter,
including limits for unauthenticated failures.

## Metrics

`GET /metrics` returns aggregate Prometheus text metrics for HTTP traffic,
latency, errors, supported drafts, abstentions, and draft failures. It never
uses ticket text, tenant IDs, or API keys as metric labels. Restrict this route
at the production gateway and configure dashboards and alerts before accepting
customer traffic.

## Locked dependencies and scans

`requirements.lock` contains the hash-locked runtime environment and
`requirements-test.lock` contains the hash-locked CI/test environment. Regenerate
them deliberately with the commands recorded at the top of each file, review
the diff, and run:

```bash
uvx pip-audit==2.10.1 --require-hashes --disable-pip -r requirements.lock
```

The GitHub quality gate also scans repository content for secrets and scans the
built image for fixed high and critical vulnerabilities. Scanner versions and
GitHub Actions are pinned in the workflow. The image build pulls the current
base tag and upgrades the installed OpenSSL runtime packages from Debian's
security repository before the scan runs.

The secret scan has one narrow exception:
`data/kubernetes/knowledge.json`. This generated corpus contains example JWTs
and Docker configuration values copied from pinned official Kubernetes
documentation, which trigger generic credential detectors. The exception does
not cover application code, configuration, scripts, tests, or project
documentation. The corpus source commit and SHA-256 checksum remain recorded in
`data/kubernetes/manifest.json` and are checked by the regression suite.

## Remaining production controls

Before handling confidential or customer support data, add a shared edge rate
limiter, managed secrets, centralized metrics and alerting, structured log
collection with retention controls, load and failure testing, deployment
rollback verification, and an availability target. Passing the current CI gate
does not by itself qualify answer accuracy or make the Render free-tier demo a
production service.
