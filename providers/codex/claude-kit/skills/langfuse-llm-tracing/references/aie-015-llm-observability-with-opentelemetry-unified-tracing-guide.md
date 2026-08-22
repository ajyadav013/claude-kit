---
source: https://docs.base14.io/guides/ai-observability/llm-observability/
author: base14 (Scout documentation)
license-note: ideas absorbed in own words; no text or code reproduced
---

# One trace ID spans HTTP, agent, and model call — LLM cost is a span attribute

## What it adds beyond the primary

This is the most concrete attribute-level walkthrough in the cluster: it names the
GenAI span keys (`gen_ai.operation.name`, `gen_ai.provider.name`,
`gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons`, `server.address`)
and the three instrument names that carry the numbers —
`gen_ai.client.token.usage` (histogram, split by a `gen_ai.token.type` of input
or output), `gen_ai.client.operation.duration`, and `gen_ai.client.cost` (a USD
counter). It adds three things the primaries leave implicit. First, a
three-layer span model: auto-instrumentation already captures the outbound HTTP
call because the Python Anthropic and OpenAI SDKs ride on httpx, but that span
knows nothing about model or tokens, so a custom `gen_ai.chat` span wraps it and
a custom `invoke_agent` span wraps that to carry business context. Second, cost
is computed client-side from a per-model price table keyed on the *exact dated*
model id the provider echoes back, then emitted with dimensions like agent name
and tenant/campaign id so spend can be summed per agent rather than per service.
Third, evaluation is treated as telemetry rather than as an offline artifact: a
`gen_ai.evaluation.result` span event plus a normalised score histogram makes
output quality a dashboard series and an alertable trend.

## Primary source for this cluster

[aie-012-opentelemetry-for-ai-observability-what-it-covers-and-wher.md](aie-012-opentelemetry-for-ai-observability-what-it-covers-and-wher.md)

## Fidelity check

1. Claim: one trace connects HTTP entry, agent orchestration, model call, and
   database query. Support: the capture opens by framing the "unified trace" as
   a single trace id across every layer, and shows a worked tree where a
   FastAPI request contains SQLAlchemy queries, a pipeline span, per-agent
   spans, LLM spans, and the outbound provider HTTP calls.
