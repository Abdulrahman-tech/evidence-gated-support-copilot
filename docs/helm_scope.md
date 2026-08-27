# Helm Support Corpus Scope

The first adjacent corpus is an isolated Helm 3 documentation candidate. It
uses the official `helm/helm-www` repository pinned to commit
`dde63e420fc8f492be46f2637411cf2a805fc4f9` and only reads
`versioned_docs/version-3`, identified by the repository as Helm 3.19.0.

The build contains 712 unique sections from 126 English documentation pages.
Every section retains its source path, pinned commit, official GitHub URL,
product area, and `helm-v3` tenant identifier. The Helm website states that its
documentation is CC BY 4.0; the website repository itself carries an MIT
license. Both are recorded separately in the corpus manifest.

This corpus is machine-ingested and unreviewed. It remains physically separate
from Kubernetes core and is not enabled for runtime routing. Helm 4 is the
current major version, while the 2025 source-yield pilot predates its release;
mixing Helm 3 and Helm 4 passages without version-aware routing would risk
contradictory answers.

The six Helm-routed pilot titles are used only for an unlabelled retrieval
diagnostic. They remain excluded from evaluation, and the existing global
retrieval-confidence threshold is not considered calibrated for Helm. Runtime
integration requires source-content adjudication, a fresh version-specific
development and validation set, and Helm-specific retrieval and abstention
gates.

Codex subsequently opened all six pilot sources and completed an AI-assisted
diagnostic audit against the pinned corpus: 2 supported and 4 unsupported. The
supported cases achieved Recall@1 of 0% and Recall@3 of 50%; only 50% of the
unsupported cases abstained under the legacy threshold. This tiny, non-human
sample is not an evaluation result, but it is sufficient to keep runtime Helm
routing disabled. One supported whitespace-control answer did not appear in
the top 100 lexical results, providing a concrete development target for
retrieval improvements.
