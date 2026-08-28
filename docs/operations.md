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

## Correlated logs

Every HTTP response includes `X-Request-ID`. A caller-supplied ID is retained
only when it contains safe ASCII identifier characters and is at most 128
characters; otherwise the service generates a UUID. Each request emits a
single-line JSON `http_request_completed` event with the request ID, method,
path, status, and duration. Draft completion events use the same request ID.
These events omit ticket text and bearer keys.

Render captures the process output, providing one central log stream for this
single-instance demo. A production deployment still needs defined retention,
access controls, export, queries, and alerts in a proper log platform.

## External smoke monitor

`.github/workflows/live-smoke.yml` checks the public health, readiness, metrics,
privacy, and security-header contracts every six hours and on manual dispatch.
A failed workflow is visible in GitHub Actions and can notify maintainers when
their GitHub Actions notification settings are enabled.

This is a zero-cost portfolio monitor, not real-time availability monitoring.
Its six-hour interval, GitHub scheduling delays, and the Render free-tier cold
start make it unsuitable for an SLA.

The monitor also compares `/readyz.release` with the commit that triggered the
workflow. Render supplies this value through its documented
`RENDER_GIT_COMMIT` runtime variable. A healthy process running the wrong
release therefore fails the operational contract instead of appearing healthy.

## Failure injection and rollback drill

`tests/test_failure_injection.py` injects three bounded failures without calling
paid providers: a verifier timeout, a verifier response containing an invalid
quote, and authenticated request overload. The expected outcomes are safe
abstention for evidence failures, HTTP 429 with `Retry-After` for overload, and
continued health/readiness responses.

Verify a deployed or restored release explicitly with:

```bash
python scripts/check_live_service.py \
  --expected-release FULL_COMMIT_SHA
```

For a Render rollback drill, record the current and previous known-good commit
SHAs, deploy the current release, verify its exact SHA, select **Rollback** on
the previous successful Render deploy, and verify the previous SHA. Finally,
redeploy the current commit and verify its SHA again. Stop and investigate if
any contract check fails; do not continue customer traffic on an unidentified
release. The drill is complete only when the current release has been restored.

## Bounded load check

Run the load check locally with a dedicated non-production key:

```bash
export SUPPORT_COPILOT_LOAD_TEST_API_KEY='replace-with-a-test-key'
python scripts/load_test_api.py \
  --base-url http://127.0.0.1:8000 \
  --requests 20 \
  --concurrency 4 \
  --max-p95-seconds 2
```

The command fails when its error-rate or p95-latency threshold is exceeded. It
refuses remote targets unless `--allow-remote` is supplied, and reads the key
from the environment rather than a command-line argument. Remote tests must be
authorized and sized below the deployment's rate and capacity limits.

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
limiter, managed secrets, a production metrics/log backend with paging alerts,
larger sustained load and platform-level dependency failure tests, and an
availability target. The current structured logs, external smoke check, bounded
failure injection, release identity, and load command are operational
foundations, not substitutes for those platform controls. Passing the current
CI gate does not by itself qualify answer accuracy or make the Render free-tier
demo a production service.
