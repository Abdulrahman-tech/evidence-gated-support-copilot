# Kubernetes Reference Implementation Scope

The Kubernetes track assists platform engineers, SREs, and application
developers with evidence-bound answers to Kubernetes support questions. It is
not an autonomous remediation agent. The default behavior is read-only,
fail-closed, and subject to human approval.

The official knowledge corpus is built from the English user documentation in
`kubernetes/website`, pinned to commit
`25f3dcbed7429ebe20174ccc7000428d0f0aedda`. It includes concepts, setup,
tasks, tutorials, and reference pages. Contributor-only documentation is out of
scope. Kubernetes documentation is distributed under CC BY 4.0.

The first production boundary is deliberately limited to Kubernetes core. A
deterministic pre-retrieval router abstains when a question explicitly depends
on an uncovered ecosystem corpus such as Helm, Argo CD, Prometheus Operator,
KEDA, EKS, AKS, GKE, an ingress controller, cert-manager, or a service mesh.
These routed abstentions do not call the evidence verifier and therefore avoid
spending hosted-model tokens on questions the approved corpus cannot answer.
The API returns the selected `scope_route` so coverage and demand can be
measured before any adjacent corpus is added.

The deterministic `kubernetes_scope_v1` router was run over the excluded
60-case source-yield pilot using question titles only. It explicitly routed 16
cases (26.7%) away from the core corpus: Helm 6, Argo CD 3, application/vendor
ecosystems 3, and one each for AKS, GKE, Prometheus ecosystem, and service
mesh. The other 44 cases proceed to core retrieval; they are not assumed to be
supported. Because the pilot was deliberately stratified for source-yield
research, these counts rank expansion demand within the pilot and are not a
population-prevalence estimate. Helm is the first adjacent-corpus candidate.

Authentic candidate questions come from Stack Overflow through the documented
Stack Exchange API. Every stored candidate retains its question URL, author
attribution, timestamps, tags, and content-license metadata. Question and
answer bodies are not redistributed by the initial collector.

The first 60 cases are a source-yield pilot, not an evaluation split. Pilot
labels may change source-selection rules, so pilot cases are permanently
excluded from development, validation, and locked-test metrics. No hosted model
or Groq call is permitted during corpus construction, candidate selection,
manual labeling, or retrieval evaluation.
