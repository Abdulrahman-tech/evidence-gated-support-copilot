# Product scope contract

## Primary product

This repository builds one primary product: an evidence-gated support copilot
for Kubernetes core documentation. The runtime tenant is `kubernetes`; the
Docker image and Render service ship only the pinned Kubernetes corpus.

The release claim remains **production-minded portfolio beta, not production
ready** until the Kubernetes gates in `production_readiness.md` pass. Results
from historical mixed-support data or experimental corpora cannot satisfy those
gates.

## Experimental work

Helm remains an offline adjacent-corpus candidate. Medusa is a paused research
archive. Neither may be enabled in the runtime, presented as the primary product,
or used as Kubernetes release evidence without an explicit scope-contract
change and matching tests.

## Drift prevention

`config/product_scope.json` is the machine-readable source of truth.
`scripts/check_product_scope.py` verifies:

- the primary product and tenant are Kubernetes;
- the corpus commit and checksum are pinned;
- Docker and Render use only the Kubernetes corpus;
- the public readiness claim remains honest; and
- the active benchmark milestone is the Kubernetes recovery source audit and
  cannot be mistaken for release evaluation; and
- the Medusa pilot remains paused and is not described as production.

The check runs on every push and pull request. An intentional product change
must update the contract, deployment configuration, documentation, and tests in
one reviewed commit.
