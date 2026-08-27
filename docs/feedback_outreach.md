# Developer-tool feedback campaign

## Goal and boundary

Ask 20 developer-tool teams whether evidence-bound support drafting solves a
real workflow problem. This is research, not a bulk sales campaign. Send at
most five personalized messages per day, use public community or company
channels, and stop after one follow-up. Do not open a technical support ticket
while pretending to have a product issue.

No message has been sent yet. Review the case-study link and each personalized
opening before sending from your own account.

## Priority targets

| # | Company | Why it fits | Best public route | Personalized opening |
|---:|---|---|---|---|
| 1 | PostHog | Publicly emphasizes engineering-led technical support | [PostHog: ask a question](https://posthog.com/) | “Your engineering-led support model made PostHog my clearest design-partner candidate.” |
| 2 | Render | Handles deployment and infrastructure troubleshooting | [Render Developer Relations](https://render.com/docs/community) | “I’m testing whether evidence trajectories can shorten deployment-support review without widening Render’s support scope.” |
| 3 | Pulumi | Kubernetes/IaC questions require precise versioned evidence | [Pulumi community and support](https://www.pulumi.com/docs/support/getting-support/) | “Pulumi’s mix of Kubernetes, cloud providers, and SDK versions is exactly where broad RAG answers become unsafe.” |
| 4 | Grafana Labs | Large technical-support surface across observability tools | [Grafana community and contact](https://grafana.com/help/) | “I designed the copilot to route ecosystem questions and expose why it abstained—useful for Grafana’s broad support surface.” |
| 5 | Temporal | Documentation-heavy distributed-systems support | [Temporal Slack and forum](https://docs.temporal.io/) | “Temporal support questions often hinge on one execution or failure semantic, which is the evidence problem I’m studying.” |
| 6 | Tailscale | Strong human support and developer community | [Tailscale community](https://tailscale.com/about-community) | “Tailscale’s emphasis on human support is why every draft in my prototype remains review-required.” |
| 7 | Inngest | Durable execution platform with Discord and support team | [Inngest contact and community](https://www.inngest.com/get-in-touch) | “Inngest’s support surface spans SDKs, deployment providers, and workflow semantics—the exact routing problem I’m testing.” |
| 8 | Trigger.dev | Open-source workflow platform with AI tooling | [Trigger.dev community](https://trigger.dev/) | “Your agent tooling and observable runs make trajectory-level evaluation a particularly relevant feedback topic.” |
| 9 | Better Stack | Observability and incident tooling with Kubernetes users | [Better Stack help](https://betterstack.com/help) | “I’m exploring whether citation and abstention trajectories can help support engineers review infrastructure answers faster.” |
| 10 | incident.io | Publicly states that it wants to talk with users | [incident.io contact](https://docs.incident.io/help/contact) | “Your documentation says you optimize for talking to users, so I’m asking for product feedback rather than submitting a support issue.” |
| 11 | Axiom | Event-data platform with active developer Discord | [Axiom community route](https://axiom.co/docs/reference/cli#get-help) | “Axiom’s high-context observability questions are a strong test of exact evidence versus merely related documentation.” |
| 12 | Clerk | SDK-heavy authentication support across frameworks | [Clerk contact and Discord](https://clerk.com/contact) | “Authentication support is where version and framework qualifiers make plausible AI answers especially risky.” |
| 13 | LaunchDarkly | Already uses generative AI in support workflows | [LaunchDarkly help center](https://support.launchdarkly.com/hc/en-us) | “Because LaunchDarkly already supports optional generative-AI ticket processing, I’d value feedback on my evidence and trajectory gates.” |
| 14 | Netlify | Deployment support plus an active public forum | [Netlify support](https://www.netlify.com/support/) | “Netlify’s boundary between platform issues and third-party code is similar to my deterministic scope router.” |
| 15 | Vercel | Large developer-support and community surface | [Vercel contact and community](https://vercel.com/contact) | “I’m testing whether explicit routed abstention is more useful than broad answers for platform-versus-framework questions.” |
| 16 | Supabase | Database, auth, storage, and edge-function support | [Supabase GitHub discussions](https://github.com/orgs/supabase/discussions) | “Supabase’s product breadth makes corpus boundaries and tenant-safe evidence particularly important.” |
| 17 | Neon | Postgres platform with active Discord and support | [Neon documentation](https://neon.com/docs/introduction/support) | “Neon’s mix of Postgres semantics and platform behavior is a useful test for direct-evidence requirements.” |
| 18 | Railway | Deployment platform with a public help community | [Railway Central Station](https://station.railway.com/) | “Railway deployment questions often include adjacent framework problems; I’m testing an explicit platform-scope router.” |
| 19 | Fly.io | Infrastructure platform whose free users rely on community | [Fly.io community](https://community.fly.io/) | “Fly.io’s networking and distributed-system questions are a strong fit for evidence-first, human-reviewed drafting.” |
| 20 | Sentry | Error-monitoring platform with an active open-source community | [Sentry GitHub discussions](https://github.com/getsentry/sentry/discussions) | “Sentry’s support questions connect stack traces, SDK versions, and docs; I’d value your view on citation-safe drafting.” |

## Short outreach message

**Subject:** Could I get 15 minutes of feedback on an evidence-first support copilot?

```text
Hi [name/team] — [personalized opening]

I built a small Kubernetes support copilot that routes out-of-scope questions,
requires exact documentation quotes, and exposes a five-stage trajectory for
every cited answer or abstention. It is a portfolio prototype, not a sales pitch.

Would someone in Developer Relations, Support Engineering, or Product be open
to a 15-minute critique? I want to learn whether this control model addresses a
real support bottleneck before I invest in a larger independent benchmark.

Case study: [PUBLIC_CASE_STUDY_URL]
Demo: [PUBLIC_DEMO_URL or “I can share a local walkthrough”]

Thank you,
Abdullateef
```

## Questions for each conversation

1. Where do support engineers lose the most time: finding evidence, checking
   correctness, or rewriting answers?
2. Would an explicit abstention reason help, or merely create another queue?
3. Which trajectory states would you want aggregated in an operations dashboard?
4. What data is too sensitive to send to a hosted verifier?
5. What would a two-week, read-only pilot need to prove?

## Tracking fields

Record company, contact route, date sent, personalized hook, response,
interview date, strongest pain, requested integration, objection, and follow-up
date. Do not record private information that the contact did not provide for
this conversation.
