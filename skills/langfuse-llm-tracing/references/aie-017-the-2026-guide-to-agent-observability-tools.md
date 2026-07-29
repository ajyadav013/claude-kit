---
source: https://montecarlo.ai/blog-agent-observability-tools
author: Monte Carlo (Virna Sekuj)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Agent observability is five categories; only OTel instrumentation travels

## What it adds beyond the primary

The primary establishes the two-layer thesis (OTel as neutral data plane,
quality judgement as a separate control plane above it). This vendor survey
adds the buyer's map underneath that thesis: it sorts roughly eighteen tools
into five categories keyed to five different questions — what did the agent
do (tracing), was the output good (evaluation), how do I route and cap the
traffic (gateway), can one platform hold classic ML and GenAI (hybrid), can
this sit beside my existing infra monitoring (broad APM) — and argues each
category has a structural ceiling rather than a feature gap. Two of those
ceilings are new material for the kit. A gateway sees requests, not
reasoning: it can tell you an agent made nine model calls but not that the
nine were one plan, so request-level logs never reconstruct a span tree, and
its inline position taxes every user request with extra latency. And
network-hosted LLM-as-a-judge has a latency budget problem — fine for
offline scoring, unusable as an inline guardrail, because you cannot add
hundreds of milliseconds and a per-check API bill to every response, which
is why teams end up grading a small sample of production traffic instead of
all of it. The escape from that is small purpose-built scoring models
running inside your own perimeter. It also makes the portability argument
concrete with dates: ClickHouse acquired Langfuse in January 2026, Cisco
announced intent to acquire Galileo in April 2026, so instrumentation you
cannot re-point is a bet on a vendor's ownership staying put.

Ideas worth carrying:

- **Pick the category before comparing features.** Tracing, evaluation,
  gateway, hybrid ML/LLM, and broad-APM tools answer different questions;
  most teams need two of them paired, not one that claims all five.
- **Seven filters that sort candidates fast** — was it built for deeply
  nested multi-step agent runs or for single LLM calls with agent support
  retrofitted; does it score faithfulness, relevance, hallucination, safety
  and tool-choice correctness or only log latency, tokens and cost; what is
  the licence and can you self-host (the field spans MIT, Apache 2.0, AGPL,
  Elastic License 2.0, and fully closed); OTel-native or proprietary SDK;
  can PMs, QA and domain experts review outputs or is it engineers-only;
  is billing per trace, per seat, per log or per gigabyte (these look alike
  on a pricing page and diverge sharply at production volume); and does it
  close the loop by turning production failures back into eval cases.
- **Instrumentation is the lock-in, not the dashboard.** A decorator-based
  proprietary SDK is low-friction to adopt and non-portable afterwards;
  plain OTel spans following the GenAI semantic conventions can be re-pointed
  at a different backend without touching application code.
- **Agent-shaped failure modes deserve first-class tracking** — infinite
  loops that re-read the same document, wrong-tool selection, and the
  reasoning that led into a tool call, not merely the fact of the call.
- **Vector-store health is a RAG failure origin**, and embedding-space
  cluster analysis finds classes of failure (for example a dense blob of bad
  answers all about content the retriever never indexed) that no amount of
  scrolling a trace list will surface.
- **Broad APM platforms win on correlation, lose on quality.** Their
  advantage is that the model call, the vector store, the Postgres query and
  the rate-limited downstream API are all already instrumented in one place;
  their consistent weakness is output-quality evaluation, hence the common
  pairing with a dedicated eval tool.
- **The article's closing argument is the publisher's own pitch** and should
  be read as such, but the observation under it is sound: a trace can look
  perfectly healthy while the answer is wrong, because the agent faithfully
  used the numbers it was handed and the damage happened upstream in a stale
  table or broken pipeline. Data freshness and agent behaviour are usually
  watched by two different systems that never meet.
- Framing statistics, from the publisher's own enterprise survey: 73% say
  they will not ship an agent without monitoring and alerting in place, and
  53% expect to significantly redesign agents they have already deployed.

## Primary source for this cluster

[aie-012-opentelemetry-for-ai-observability-what-it-covers-and-wher.md](aie-012-opentelemetry-for-ai-observability-what-it-covers-and-wher.md)

## Fidelity check

1. Claim: five categories keyed to five questions. Support: the capture's
   section on how to choose lists tracing / evaluation / gateways / hybrid
   platforms / broad platforms each against a question.
