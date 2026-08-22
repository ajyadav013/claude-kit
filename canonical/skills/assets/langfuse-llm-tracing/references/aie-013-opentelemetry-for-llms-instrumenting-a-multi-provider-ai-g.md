---
source: https://www.truefoundry.com/blog/opentelemetry-llm-gateway-instrumentation
author: Boyu Wang (TrueFoundry)
license-note: ideas absorbed in own words; no text or code reproduced
---

# An LLM gateway needs no new observability concept, just the right span tree

## What it teaches

LLM observability does not require a bespoke telemetry stack; it requires
applying OpenTelemetry's GenAI semantic conventions (the `gen_ai.*`
namespace) to the proxy layer that already sits in front of every model
call. The piece walks the whole instrumentation surface of a gateway that
fronts twenty-plus providers: which attributes to set, what span kinds and
span names the spec prescribes, how a provider fallback is represented
structurally rather than as a special event, how to flatten each vendor's
idiosyncratic error payload into a small normalized vocabulary while
retaining the raw detail, how to derive per-span and per-trace cost from
usage tokens plus a maintained pricing table, how W3C `traceparent` binds
application spans to gateway spans, and how streaming responses are timed
without closing the span early. It closes with exporter wiring, sampling
strategy, and cardinality warnings. The recurring theme: get the span tree
shape right and the dashboards, alerts, and cost reports fall out of it.

## Key patterns & decisions

- **`gen_ai.*` is a moving target — plan for attribute churn.** The GenAI
  semantic conventions were still in Development status at semconv v1.36.0.
  `gen_ai.system` is deprecated in favour of `gen_ai.provider.name`, and
  errors use the standard `error.type` rather than a GenAI-specific field.
  Most instrumentation libraries in the wild still emit the older names, so
  backends should accept both, and `OTEL_SEMCONV_STABILITY_OPT_IN` should be
  set deliberately rather than left to defaults.

- **Three span kinds, one shape.** One SERVER root span per inbound request;
  CLIENT spans for outbound provider calls; INTERNAL spans for work inside
  the gateway process such as PII redaction or schema validation. Inference
  span names follow `{operation} {model}` (e.g. a chat operation plus the
  model id), not free-form labels. This consistency is what makes dashboards
  portable between teams.

- **Fallback is a sibling span, not a new concept.** When the primary
  provider returns an overload error and the gateway reroutes, the trace
  simply carries two CLIENT provider spans under one root: the first with
  ERROR status, the second OK. The root reflects what the caller actually
  experienced. Fallback hit rate, added latency, and cost impact then become
  a single TraceQL-style query: roots that succeeded while one of their
  provider children failed.

- **Normalize errors to a low-cardinality vocabulary, keep the raw field
  beside it.** A handful of values — rate limited, quota exceeded,
  overloaded, provider unavailable, timeout, invalid request, content
  filtered — drives cross-provider alerts, while a provider-scoped attribute
  preserves the vendor's original code for forensics. Low cardinality on the
  normalized field, high cardinality on the raw one; both are needed.

- **Requested model and served model are different attributes.**
  `gen_ai.request.model` records what the client asked for;
  `gen_ai.response.model` records what the provider actually ran, because
  friendly model aliases resolve to dated snapshot versions.

- **Cost is derived, and cached tokens are a double-counting trap.** No
  provider emits cost, so the gateway computes it from usage attributes and
  its own pricing table. Per the spec, `gen_ai.usage.input_tokens` already
  includes both cache-read and cache-creation tokens; billing the full input
  count at the standard rate and then adding the cache lines overcharges.
  Subtract both first. Fallback costs are additive — a failed primary call
  still consumed input tokens — so each provider span carries its own cost
  and the root sums them.

- **Attribution is the application's job, propagated by the gateway.** The
  caller tags its span with team, feature, or cost-centre attributes; the
  gateway preserves them down the tree via baggage and parent-span
  attributes. That lets one dashboard answer per-team, per-feature, and
  per-customer spend questions without the gateway knowing anything about
  the organisation's structure.

- **Streaming: keep the span open, emit TTFT as an event.** Time to first
  chunk is recorded as a span event while the stream is still running; the
  span closes only after the last chunk, because providers report final
  token usage in the terminating chunk or stop event. An exporter that
  flushes early records zero output tokens and silently breaks cost
  attribution. The GenAI metrics spec also defines operation duration,
  time-to-first-chunk, and time-per-output-chunk metrics.

- **Decouple export from the request path, and sample in two tiers.** The
  described gateway ships spans asynchronously (over a message bus) so an
  observability backend outage cannot degrade inference availability. For
  volume, use head-based probability sampling on the happy path plus
  tail-based sampling at the collector to retain all error and slow traces.
  High-cardinality payloads such as full prompts belong in events or logs,
  not span attributes, and prompt/completion capture should be opt-in and
  limited to sampled traces because of PII and span-size blowup.

## When to apply / trade-offs

Apply this when LLM traffic already flows through a shared proxy or gateway
and you need a single place to learn what failed, what it cost, and which
team is accountable, spanning several providers. Instrumenting at the gateway is the
highest-leverage move precisely because it is the single chokepoint — you
get every application's calls without touching every application. The costs
are real: the pricing table must be kept current or cost attribution rots
silently; the semantic conventions are pre-stable, so attribute renames will
break saved queries; and cardinality discipline has to be enforced or the
observability bill starts to rival the inference bill. This is the wrong
investment if calls go direct to one provider from one service (vendor LLM
tracing tools cover that with far less work), if you are pre-production and
would be better served by capturing full prompt/response pairs for eval
purposes, or if you have no OTel pipeline at all — the article explicitly
assumes an existing OTel deployment and only shows how to extend it.

## Fidelity check

1. Claim: the GenAI conventions are pre-stable and `gen_ai.system` has been
   renamed. Support: the capture states the conventions are in Development
   status as of OTel semconv v1.36.0, that `gen_ai.system` is deprecated in
   favour of `gen_ai.provider.name`, and that `OTEL_SEMCONV_STABILITY_OPT_IN`
   is the mitigation when upgrading.
2. Claim: span kinds are SERVER root, CLIENT provider, INTERNAL guardrail,
   with `{operation} {model}` inference span names. Support: the capture's
   section on the gateway span hierarchy states each of these explicitly and
   contrasts the prescribed name format against ad-hoc alternatives.
3. Claim: input token counts include cached tokens and must be subtracted
   before applying the input rate. Support: the capture's cost section states
   the spec includes cache-read and cache-creation tokens in
   `gen_ai.usage.input_tokens` and warns that not subtracting them
   overcharges the cache-read portion and double-counts cache writes.
