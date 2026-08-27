# Evidence-Gated Support Copilot — Kubernetes Local Demo

This demo runs without OpenAI, Groq, or any paid API. It uses the pinned
Kubernetes documentation corpus, local BM25 retrieval, deterministic scope
routing, and an explicitly non-production lexical-overlap verifier.

## Run locally

From the repository root:

```bash
python -m pip install -e .
export SUPPORT_COPILOT_KNOWLEDGE_PATH=data/kubernetes/knowledge.json
export SUPPORT_COPILOT_API_KEYS='{"local-demo-key":"kubernetes"}'
export SUPPORT_COPILOT_EVIDENCE_VERIFIER=local_demo
export SUPPORT_COPILOT_MINIMUM_SCORE_RATIO=1.0
uvicorn support_copilot.api:create_app_from_env --factory --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, enter `local-demo-key`, and try the three example
buttons. The key is a local demonstration value, not a deployable secret.

## Run with Docker

```bash
docker build -t evidence-gated-support-copilot:local .
docker run --rm -p 8000:8000 \
  -e SUPPORT_COPILOT_API_KEYS='{"local-demo-key":"kubernetes"}' \
  -e SUPPORT_COPILOT_EVIDENCE_VERIFIER=local_demo \
  -e SUPPORT_COPILOT_MINIMUM_SCORE_RATIO=1.0 \
  evidence-gated-support-copilot:local
```

The image runs as a non-root user and includes a `/healthz` container health
check. The default image contains only the pinned Kubernetes corpus; Helm
remains excluded from runtime retrieval.

## Expected demonstration

| Question type | Expected behavior |
|---|---|
| Kubernetes Service/ClusterIP example | Returns one exact official quote and source URL |
| Explicit Helm question | Routes to `helm` and abstains before verifier use |
| Unrelated billing question | Abstains because retrieval confidence is insufficient |

Every result retains `needs_human_review: true`.

## Honest boundary

`local_demo` uses conservative term overlap, not semantic verification. It is
included so the product can be demonstrated at zero cost; it must not be used
as evidence of production answer accuracy. The default verifier remains
`fail_closed`, and production readiness remains blocked on independent
Kubernetes evaluation, verifier qualification, gateway controls,
observability, load testing, and deployment security.
