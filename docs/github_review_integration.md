# Review-first GitHub Issues integration

This integration turns signed `issues.opened` webhooks into tenant-isolated
review records. It deliberately contains no GitHub token, comment endpoint, or
autonomous posting code. Approving a review records the final answer only.

## Configuration

Both variables are required together:

```bash
export SUPPORT_COPILOT_GITHUB_WEBHOOK_SECRET='replace-with-a-long-random-secret'
export SUPPORT_COPILOT_GITHUB_REPOSITORIES='{"owner/repository":"kubernetes"}'
```

The repository must be an exact `owner/repository` match and the tenant must
exist in the pinned knowledge base and API-key mapping. Keep the webhook secret
in the deployment secret manager, never in `render.yaml`, shell history, source
control, screenshots, or logs.

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

The current queue is process-local memory. Records and delivery IDs disappear
on restart and are not shared across replicas. This is safe for demonstrating
the review contract, but a real support workflow requires a durable database
with unique delivery-ID constraints, encrypted storage, retention/deletion
rules, backups, migrations, and access auditing before enabling real customer
repositories.
