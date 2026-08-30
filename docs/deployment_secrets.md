# Deployment secrets

The production authentication path accepts a read-only JSON file that maps
SHA-256 bearer-key digests to tenant IDs. The service hashes the presented
bearer key and compares only digests using constant-time comparison. Raw keys
are not stored in the server file, process environment, image, or logs.

## Generate an initial key

Create the file outside the repository. The command refuses to overwrite an
existing file and creates it with mode `0600`:

```bash
python scripts/create_api_key_secret.py \
  --tenant kubernetes \
  --output /secure/path/support-copilot-api-key-hashes.json
```

The command displays the strong random bearer key once. Put that raw value in
the calling client's secret manager. Do not paste it into source control,
shell profiles, container images, tickets, or documentation.

## Mount the server secret

Configure the service with:

```bash
export SUPPORT_COPILOT_KNOWLEDGE_PATH=data/kubernetes/knowledge.json
export SUPPORT_COPILOT_API_KEY_HASHES_FILE=/run/secrets/support_copilot_api_key_hashes
uvicorn support_copilot.api:create_app_from_env \
  --factory --host 0.0.0.0 --port 8000
```

In Docker, Kubernetes, or a cloud platform, use its secret-volume mechanism to
mount that path read-only. Do not use `SUPPORT_COPILOT_API_KEYS` in a deployed
environment; it exists only for the zero-cost local demo.

The file format supports multiple digests so a key can be rotated without
downtime. Add the new digest, deploy the updated secret, migrate the client,
then remove the old digest and redeploy. Never reuse a key across tenants or
environments.

## Isolate GitHub review access

GitHub review endpoints use a separate credential set from draft generation.
When webhook ingestion is enabled, configure a private reviewer key as a
SHA-256 digest mapping:

```bash
export SUPPORT_COPILOT_REVIEW_API_KEY_HASHES='{"<sha256-digest>":"kubernetes"}'
```

Keep the raw reviewer key only in the reviewer's secret manager. A draft key
cannot list, approve, or reject reviews, and a reviewer key cannot generate
drafts. The application refuses to start if a GitHub repository tenant lacks a
reviewer credential or if the same key is used for both capabilities.

## Controls outside the application

The mounted file solves secret delivery, not the complete network boundary. A
real deployment must also terminate TLS at a trusted ingress, enforce request
rate limits, restrict secret-file access to the workload identity, audit secret
reads and rotations, and keep development and production secret stores
separate.
