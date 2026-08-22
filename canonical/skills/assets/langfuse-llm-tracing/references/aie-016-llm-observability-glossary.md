---
source: https://www.guild.ai/glossary/llm-observability
author: Guild.ai
license-note: ideas absorbed in own words; no text or code reproduced
---

# LLM observability's blocker is adoption discipline, not missing tooling

## What it adds beyond the primary

Largely corroborates the primary's OpenTelemetry framing, but contributes four
things the primary does not. First, a quantified adoption gap: citing Grafana's
2025 observability survey, roughly 47% of companies are investigating or
building a POC for LLM observability while only about 7% run it in production
in any serious way — useful as the reason a kit rule should exist at all.
Second, an explicit ordering for what to instrument: start with per-step
latency, input and output token counts, cost per request, error rate, and time
to first token, and only layer on quality signals (hallucination rate,
relevance scoring, user feedback) once the tracing foundation is stable. Third,
a concrete cost-attribution dimension list — user, session, geography, feature,
model, and prompt version — with prompt version being the axis the kit
currently never names; the worked example is an agent fleet where one
low-stakes agent runs on an expensive model that a cheap one handles at roughly
a twentieth of the cost. Fourth, it insists request-shaping parameters like
temperature and top_p belong in span metadata, because a small temperature move
changes both output quality and spend in ways latency graphs never reveal.

Its privacy stance is sharper than a generic redaction rule: redact at the
instrumentation layer before data reaches the backend, sample routine traffic
while capturing failures in full, store hashes when you need correlation
without raw text, and keep prompt retention short — with an explicit redaction
stage between instrumentation and storage for SOC 2, HIPAA, or GDPR
environments. It also warns that telemetry storage can exceed the cost of the
primary infrastructure being observed, so "capture everything" is a budget
decision, not a default. Two framings are worth borrowing verbatim as ideas:
monitoring tells you something broke against a preset threshold while
observability lets you ask questions you did not pre-plan, so you need both;
and traces nobody acts on are just expensive logging, which makes ownership,
policy, and automated guardrails part of the observability deliverable rather
than a follow-up. Finally it names the drift case the kit's eval rule implies
but does not state — a provider ships a model update, answers get subtly
shorter and less specific, and the regression is invisible unless quality
scores are joined to model-version metadata.

## Primary source for this cluster
`aie-012-opentelemetry-for-ai-observability-what-it-covers-and-wher.md`
(secondary primary: `aie-013-opentelemetry-for-llms-how-we-instrument-a-multi-provider.md`)

## Fidelity check

1. Claim: about 7% in production versus 47% investigating or building a POC.
   Support: the capture states roughly half of companies (47%) are
   investigating or building a POC while only 7% use it in production,
   extensively, or exclusively, attributed to Grafana's 2025 Observability
   Survey.
