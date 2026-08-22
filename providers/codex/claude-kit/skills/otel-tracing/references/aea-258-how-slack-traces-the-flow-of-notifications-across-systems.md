---
source: https://slack.engineering/tracing-notifications/
author: Slack Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Modeling a cross-system product funnel as distributed traces (Slack notifications)

## What it teaches

Slack's notification path touches nearly every layer of its stack — application
monolith, job queue, push infrastructure, third-party push providers, and four
different client platforms. Each layer historically logged in its own format to
its own backend, so diagnosing "why didn't I get pinged?" meant a multi-day,
multi-team archaeology dig, and notification tickets had the worst NPS and the
slowest resolution of any support category.

The fix was to stop treating this as a logging problem and treat the whole
delivery funnel as a distributed trace. The team first wrote a spec: an
idealized funnel of named stages (trigger decision, fan-out to a user, sent to
a device, received on the client, opened, rendered in-app), with agreed span
names, semantics, and tag sets that every platform must emit identically.

Two structural problems blocked a naive tracing approach. First, sampling: a
single @channel in a huge workspace fans out to hundreds of thousands of
recipients, so hanging every delivery under the sender's request trace would
produce traces with billions of spans; and support needs 100% capture, not the
1% sampling used for ordinary backend requests. Second, standard
OpenTelemetry-style instrumentation welds trace context to a single request
context, but a notification's lifecycle crosses many unrelated execution
contexts. Slack's answer: give every individual notification its own trace,
keyed by the notification's own ID reused as the trace ID, and connect it back
to the sender's (sampled) request trace with span links so causality is
preserved. Small traces, full-fidelity sampling for the flow that matters,
cheap sampling elsewhere.

A second-order payoff: because the domain ID is the trace ID, every event in a
flow is pre-sessionized with one universal join key. Product analysts computed
open-rate funnel analytics straight from the trace store, data scientists found
instrumentation bugs by mining it, and client engineers built dashboards on it
— one dataset serving debugging, support, and product analytics. Support triage
time dropped roughly 30% because a support engineer can read a single trace
instead of escalating to developers who grep five log systems.

## Key patterns & decisions

- Flow-as-trace modeling: represent a multi-system product funnel as a distributed trace with a written spec of named stages before instrumenting anything.
- One trace per fan-out target: give each notification its own trace instead of attaching billions of spans to the sender's request trace.
- Span links for cross-trace causality: link the per-notification traces back to the originating (sampled) request trace rather than parenting them.
- Per-flow sampling policy: 100% capture for the business-critical flow while ordinary request traces stay at 1%.
- Domain ID as trace ID: reusing the notification ID as trace ID gives built-in sessionization and a single join key across all events.
- Decouple trace context from request context: instrumentation must let a logical flow span many execution contexts.
- Unified span schema across heterogeneous emitters: same event format and standardized names/timestamps from backend services and iOS/Android/Desktop/web clients; service-name field identifies the emitter.
- At-source uniqueness via span IDs: unique IDs on every event kill downstream de-duplication jobs.
- Trace store as single source of truth: the same dataset serves debugging, support triage, and product funnel analytics, replacing parallel instrumentation pipelines.

## When to apply / trade-offs

Apply when a user-visible outcome is produced by a chain of independently
logged systems (delivery pipelines, checkout funnels, provisioning flows) and
"where did it drop?" is a recurring support question. The upfront cost is real:
the hard work is organizational — getting every platform team to agree on span
names, semantics, and tags — not technical. Full sampling is only viable
because the per-flow traces are small; do not attempt 100% capture on a design
that parents fan-out under one giant trace. If your tracing library hard-binds
context propagation to requests, you need a framework (or discipline) that
lets you propagate a flow ID independently. The reward compounds: one clean
dataset displaces several bespoke logging/analytics pipelines.

## Fidelity check

1. Claim: support triage got measurably faster. Capture states the customer
   experience team's time to triage notification tickets fell by 30% once they
   could read a single trace instead of escalating to developers.
2. Claim: fan-out size forced one-trace-per-notification. Capture explains that
   an @here/@channel message can push to hundreds of thousands of users across
   devices, which would have meant billions of spans in a single trace and
   would have overwhelmed ingestion and storage.
3. Claim: the trace data was reused beyond debugging. Capture describes data
   scientists building funnel/open-rate analytics dashboards from the trace
   data in the warehouse and even finding application and instrumentation bugs
   by mining it, and notes at least a dozen tracers now run in the Slack app
   using the same flow-as-trace strategy.
