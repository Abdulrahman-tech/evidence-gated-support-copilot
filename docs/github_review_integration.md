# Review-first GitHub Issues integration

This integration turns signed `issues.opened` webhooks into tenant-isolated
review records. It deliberately contains no GitHub token, comment endpoint, or
autonomous posting code. Approving a review records the final answer only.

## Configuration

All three variables are required together:

```bash
export SUPPORT_COPILOT_GITHUB_WEBHOOK_SECRET='replace-with-a-long-random-secret'
export SUPPORT_COPILOT_GITHUB_REPOSITORIES='{"owner/repository":"kubernetes"}'
export SUPPORT_COPILOT_REVIEW_DATABASE_URL='postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require'
```

The repository must be an exact `owner/repository` match and the tenant must
exist in the pinned knowledge base and API-key mapping. Keep the webhook secret
in the deployment secret manager, never in `render.yaml`, shell history, source
control, screenshots, or logs.

Startup fails closed if any variable is missing. It also rejects conflicting
SQLite and PostgreSQL settings. Store the PostgreSQL URL only in the deployment
secret manager. Remote database URLs must require TLS.

PostgreSQL is the hosted and multi-instance storage path. It uses a dedicated
`support_copilot` schema, transaction-scoped migration locking, a versioned
schema, unique delivery IDs, row locking for decisions, and bounded connection,
statement, and lock timeouts. `/readyz` returns HTTP 503 if enabled review
storage becomes unreachable.

For local or single-instance deployments on a persistent volume, set
`SUPPORT_COPILOT_REVIEW_DB_PATH` instead. SQLite uses WAL journaling, full
synchronous writes, a versioned schema, a unique delivery-ID constraint, and
owner-only permissions. Configure exactly one storage option.

For the zero-cost portfolio deployment, Neon is the current candidate because
its [Free plan](https://neon.com/pricing) has no time limit and includes a small
PostgreSQL allowance with scale-to-zero. This is not an availability SLA, and
free limits can change. Render's own
[Free PostgreSQL](https://render.com/docs/free#free-postgres) expires after 30
days and has no managed backups, so it is unsuitable for durable activation.

Configure a GitHub repository webhook to send only **Issues** events to:

```text
https://YOUR_SERVICE/v1/github/webhooks
```

Use `application/json` and the same secret configured in the service. The API
verifies `X-Hub-Signature-256` with HMAC-SHA256 before parsing or processing the
event. It accepts only `issues.opened`; other event types, actions, and
repositories are ignored.

## Review workflow

List reviews with the existing tenant API key:

```bash
curl -H 'Authorization: Bearer YOUR_TENANT_KEY' \
  https://YOUR_SERVICE/v1/reviews
```

Approve with the generated answer or an edited answer:

```bash
curl -X PATCH \
  -H 'Authorization: Bearer YOUR_TENANT_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"action":"approve","edited_answer":"Reviewed answer."}' \
  https://YOUR_SERVICE/v1/reviews/REVIEW_ID
```

Reject with `{"action":"reject"}`. A review can be decided only once. Every
response includes `posting_status: disabled`; neither action sends a GitHub
comment.

## Security and operational boundary

- Delivery IDs are claimed atomically before retrieval or verifier work, so a
  repeated delivery does not consume verifier tokens again.
- Ticket text is available only through the authenticated, tenant-isolated
  review endpoint and is omitted from logs and metrics.
- Prompt-injection and evidence-verifier failures remain abstentions requiring
  review.
- Webhook bodies are limited to 256 KB and issue tickets retain the configured
  application input limit.
- Aggregate counters report accepted webhooks, duplicates, approvals, and
  rejections without tenant, key, or ticket labels.
- Review drafts, decisions, and delivery IDs survive application reconstruction.
  An unfinished delivery claim expires after five minutes so a provider or
  process failure cannot block GitHub retries forever.

For SQLite, create an integrity-checked atomic backup without stopping the
application:

```bash
python scripts/backup_review_database.py \
  --source /durable/path/reviews.sqlite3 \
  --destination /separate/backup/location/reviews-YYYY-MM-DD.sqlite3
```

Store backups outside the application volume, encrypt them, restrict access,
and test restoration. The script refuses to overwrite an existing backup and
sets owner-only permissions.

For PostgreSQL, use the provider's restore feature and schedule encrypted
`pg_dump` exports to storage outside the database provider. Use a direct,
non-pooled connection for `pg_dump`; keep the pooled TLS URL for application
traffic. Test restoration into a separate database before relying on a backup.

SQLite is now durable across application restarts when its path is on persistent
storage. It is not shared across replicas and does not make an ephemeral host
durable. [Render documents](https://render.com/docs/free#local-files-lost-on-deploy)
that free web-service files—including SQLite databases—are lost on spin-down,
restart, or deployment, so the public free demo keeps webhook ingestion
disabled. Standard PostgreSQL support now removes that filesystem dependency,
but enabling a real repository still requires provisioned hosted storage,
defined retention/deletion rules, tested backups, access auditing, and a
controlled activation drill.

## Controlled activation and rollback

1. Provision hosted PostgreSQL and verify provider recovery and usage limits.
2. Add its pooled TLS URL, webhook secret, and one exact repository mapping to
   the deployment secret manager.
3. Deploy and require `/readyz` to report `review_only`, `postgresql`, and
   `github_posting: disabled`.
4. Create a GitHub webhook for **Issues** events only, then open a synthetic,
   non-confidential issue and verify one pending review is created.
5. Redeliver the same webhook and verify it is reported as a duplicate without
   another verifier call.
6. Approve and reject synthetic reviews, confirming that no GitHub comment is
   posted.

To roll back ingestion, remove all three GitHub integration variables and
redeploy. Do not delete the database during rollback; retain it according to the
documented retention policy.
