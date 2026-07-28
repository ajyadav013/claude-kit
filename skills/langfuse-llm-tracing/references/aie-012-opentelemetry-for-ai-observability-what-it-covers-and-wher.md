---
source: https://www.fiddler.ai/blog/opentelemetry-ai-observability-guide
author: Fiddler AI (Fiddler Team)
license-note: ideas absorbed in own words; no text or code reproduced
---

# OpenTelemetry gives LLM apps a data plane, not a quality control plane

## What it teaches

Treat AI observability as two layers, not one. OpenTelemetry is the right
foundation for the lower layer: it already carries traces, metrics and logs
through one Collector pipeline, so LLM spans correlate with the ordinary
infrastructure spans around them, and the GenAI semantic conventions give
model, token and stop-reason attributes stable names across providers. That
buys instrument-once/export-anywhere portability and a single call graph
spanning orchestrator, sub-agents, tool calls and model invocations. What it
does not buy is any notion of whether an answer was faithful, relevant,
toxic or policy-compliant — a span can record 1,200 tokens in 850 ms and say
nothing about the fact that those tokens contradicted the retrieved
documents. Telemetry is also passive by construction: it observes, it never
intercepts, redacts or blocks. The article's running example is a financial
research agent whose APM dashboards stayed green while the compliance team
found three violations by hand in one morning.

## Key patterns & decisions

- **Standardise on the GenAI attribute names, not a vendor SDK** — the
  conventions cover `gen_ai.system` (openai, anthropic, aws.bedrock),
  `gen_ai.request.model`, `gen_ai.usage.input_tokens` /
  `gen_ai.usage.output_tokens`, and `gen_ai.response.finish_reasons` (stop,
  length, tool_calls). Same attribute names across providers means swapping
  models does not invalidate dashboards or force reinstrumentation.

- **Accept that the conventions are still beta** — some attributes remain
  experimental and the GenAI SIG is still absorbing production feedback. The
  article's judgement is that the core is stable enough to build on now, but
  plan for attribute churn rather than treating the spec as frozen.

- **Data plane vs control plane is the load-bearing split** — OTel ingests
  and structures; a second layer consumes that telemetry and applies
  scoring and enforcement. Five things sit above OTel: output faithfulness
  and hallucination detection, safety/PII/policy scoring, span-level content
  quality (relevance, coherence, completeness), active guardrails, and cost
  attribution beyond raw token counts.

- **Budget the cost of judging, not just the cost of generating** — the
  article names an "Evaluation Trust Tax": the per-query price of calling an
  external LLM judge. At 500K traces/day it puts this near $260K/year, which
  never appears anywhere in the trace itself. Whether you accept that figure
  or not, the structural point stands — judge spend is invisible to token
  telemetry.

- **Multi-turn conversations silently lose parent context** — OTel context
  propagation assumes request/response. Unless the application explicitly
  carries a session-level context, each conversational turn opens a fresh
  trace and the full dialogue can no longer be reconstructed from traces.

- **Capturing prompts and completions is a governance decision, not a debug
  toggle** — full content capture puts customer data, PII and proprietary
  text into the span store. Sampling, redaction and retention policy must be
  settled before the capture flag is enabled, not after.

- **Agentic hierarchies cause span explosion** — one user request through an
  orchestrator, three sub-agents, and their tool and model calls can emit
  hundreds of spans. The recommended shape is head-based sampling around 10%
  on high-volume endpoints, plus tail-based sampling that keeps 100% of
  error traces.

- **Pick your side of the evaluation-latency trade deliberately** — scoring
  inside the request path adds latency to every response; scoring
  asynchronously means the span closes before the score exists. Sub-100ms
  in-environment scoring is what makes the synchronous option viable;
  external judge APIs are not fast enough for it.

- **In-environment evaluation is a regulatory enabler** — scoring that never
  leaves the deployment lets regulated teams (SR 11-7 in financial services,
  HIPAA in healthcare) satisfy audit requirements without exporting prompt
  content to a third-party API.

- **Known gaps worth not pretending to solve** — there is no standard
  telemetry convention for real-time evaluation of image/audio/video
  outputs, cost attribution across compound systems with mixed per-model
  pricing stays fragmented, and embedding evaluation results directly into
  spans is still only under discussion in the GenAI SIG.

## When to apply / trade-offs

Apply this the moment an LLM feature becomes multi-step — a retriever plus a
generator plus a checker — because that is where APM-style latency and error
telemetry stops explaining failures and decision lineage starts mattering.
The costs are real: content capture creates a data-governance surface,
agentic span volume can overwhelm both backend and budget without a sampling
policy, and the evaluation layer is genuinely additional infrastructure to
buy or build. Skip the full two-layer build for a single non-critical
model call behind a feature flag, where GenAI attributes on one span and
ordinary error tracking are proportionate. Note also that the source is a
vendor blog: the framing is sound and the OTel-side detail checks out, but
the closing argument — that in-environment trust models score in under
100 ms at no per-evaluation cost — is its own product pitch, and the $260K
figure is the vendor's arithmetic, not an independent benchmark. Take the
architecture, verify the economics against your own traffic.

## Fidelity check

1. Claim: the GenAI conventions standardise `gen_ai.system`,
   `gen_ai.request.model`, input/output token usage and
   `gen_ai.response.finish_reasons`. Support: the capture lists exactly
   these four attribute groups with the example values openai / anthropic /
   aws.bedrock and stop / length / tool_calls.
2. Claim: external LLM-judge evaluation at 500K traces/day is put near
   $260K/year and is called the Evaluation Trust Tax. Support: the capture
   names the term and gives that traffic volume and annual figure, while
   also noting the numbers vary by model, deployment size and traffic.
3. Claim: OpenTelemetry is passive and cannot enforce guardrails. Support:
   the capture says OTel records but does not intercept, redact or block,
   and that pre- and post-execution guardrails require active middleware.
