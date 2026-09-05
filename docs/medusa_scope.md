# Paused Medusa Research Scope

## Target user and tenant

This offline research track explored support for merchants and developers
operating Medusa stores. It is paused, not deployed, and not part of the current
Kubernetes production-readiness roadmap. The retained `medusa` tenant, corpus,
and evaluations are reproducibility artifacts only.

## Documentation coverage

The expanded candidate corpus covers 14 official documentation areas: admin
components, commerce modules, installation, deployment, tutorials,
infrastructure modules, integrations, the JS SDK, the Medusa CLI, the Next.js
starter, plugins, recipes, storefront development, and troubleshooting.

Coverage does not imply answerability. Bugs, feature requests, obsolete-version
questions, and topics not directly answered by the pinned official corpus must
still abstain or escalate rather than being forced onto a loosely related page.

## Sources and provenance

The knowledge corpus is generated from the official Medusa repository at a
pinned commit. Each section stores its source URL, repository path, commit,
tenant, and product area. Enterprise Edition paths are excluded. The corpus is
machine-ingested and must be sampled and reviewed before release.

Authentic benchmark candidates use public issue titles and answered Q&A titles
from the official Medusa GitHub repository. The project stores titles, source
URLs, accepted-answer URLs, word counts, and content hashes; it does not
redistribute discussion bodies or answers. An accepted community answer proves
that a thread was answered, but it is not official ground truth.

The current source pools contain 120 issue-title candidates and 100 unique
answered-Q&A candidates. The expanded corpus contains 3,342 unique sections
from 414 pages at commit
`c4a823a19e4787bb69f2c3238a3cb5cb0918d7cc`. Retriever predictions identify
47 high-priority Q&A rows for faster review. Candidates are not evaluation
labels: each must be mapped to an official evidence document, marked
unsupported, or excluded as outdated or ambiguous before splitting.

The first adjudicated candidate set contains 30 supported and 40 unsupported
cases; 28 outdated and 2 ambiguous cases are excluded. Development contains 42
cases and validation contains 14, with AI-assisted labels and no source overlap.
The 14 original locked-test candidates received a separate blind manual review:
11 were retained (10 supported and 1 unsupported), while 2 ambiguous and 1
outdated case were excluded. The test is independently reviewed and locked
against tuning, but its small, imbalanced sample is not a production benchmark.

## Release boundary

The project is not production-ready until all of these are true:

- an independently reviewed validation set contains at least 200 supported and
  100 unsupported cases;
- the locked test is fully reviewed without model predictions;
- lower 95% confidence bounds meet the repository's release gates;
- development-to-validation gaps stay within five percentage points;
- prompt injection, tenant isolation, provenance, latency, and fallback tests
  pass;
- unsupported and ambiguous tickets escalate to a human without a generated
  answer or unsafe action.
