---
source: https://www.braintrust.dev/articles/best-llm-gateways-observability-2026
author: Braintrust Team (Braintrust)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Instrument at the LLM gateway, not at each call site

## What it adds beyond the primary

This is a vendor comparison listicle, so its framing is self-serving, but it
carries one architectural claim the kit does not currently make anywhere: if
a service already routes model traffic through a gateway (a single endpoint
fronting OpenAI, Anthropic, Google, Bedrock, Azure, Mistral and others), that
gateway is already holding the exact fields observability needs — which model
answered, token counts, latency, and the response body — so capturing telemetry
at the routing layer avoids instrumenting every call site in the application.
It also names the evaluation dimensions to judge such a gateway on: nested span
trees (one span per LLM call, tool invocation and retrieval step, each with its
own input, output, latency, tokens, cost and error) rather than flat request
logs; cost attribution granular enough to group spend by user, feature, project
or an arbitrary custom tag rather than a single monthly invoice; automated
quality scoring on live traffic; the ability to promote a production trace into
an evaluation case so a prompt or model change can be tested against the exact
failing input; and OTLP export so LLM telemetry sits beside existing
application traces without a custom adapter. The landscape survey is useful as
a shape, not as a recommendation — OpenRouter is characterised as billing-level
visibility only (spend per model and per API key, no request-level tracing, no
OTel export); LiteLLM as a self-hosted OpenAI-compatible proxy with per-virtual-
key/user/project budget enforcement and log shipping to external backends, but
no built-in trace viewer and a Redis + PostgreSQL operational dependency;
Portkey as roughly 40 data points per request plus OTel ingestion and
workspace/team/user cost segmentation, but no native scoring. The recurring
gap across all of them is the loop back from a bad trace to a validated fix.

## Primary source for this cluster

[aie-012-opentelemetry-for-ai-observability-what-it-covers-and-wher.md](aie-012-opentelemetry-for-ai-observability-what-it-covers-and-wher.md)

## Fidelity check

1. Claim: the gateway already holds model, token usage, latency and response
   detail, so instrumenting there avoids per-call-site work. Support: the
   capture's section arguing for observability at the gateway states the
   gateway sits on every request and already has that data, and that capturing
   at that layer avoids extra instrumentation across the application.
