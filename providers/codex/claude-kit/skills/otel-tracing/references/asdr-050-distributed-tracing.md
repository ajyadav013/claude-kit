---
source: https://www.dynatrace.com/news/blog/what-is-distributed-tracing/
author: Dynatrace
license-note: ideas absorbed in own words; no text or code reproduced
---

# Distributed tracing: following one request across a microservices stack

## What it teaches

A vendor explainer (Dynatrace) on distributed tracing as the observability technique
that follows an individual request end to end through a distributed system. The
mechanism: at the entry point the request is stamped with a unique trace identifier
that travels with it through every microservice, container, and infrastructure hop
it touches. Each unit of work along the way — an API call, a database query — is
recorded as a span carrying a name, start/end timestamps, and metadata; spans nest
in parent-child relationships, and the assembled hierarchy reconstructs the
request's full path and timing. That trace-of-spans model is the article's core
technical content.

The motivating history: in monolith days you could see a transaction's whole life
inside one process, so logs and metrics sufficed. Service-oriented and then
microservice architectures scattered a single user action across many independently
deployed components, making latency root-causing genuinely hard and turning
incident response into cross-team blame sessions because nobody could tell *which*
service — and therefore which team — owned the problem. Tracing restores that
attribution: it shows precisely where in the chain time was spent or an error
occurred.

The article distinguishes tracing from logging carefully. Logs record discrete
events inside individual components; even centralized log aggregation (shipping all
service logs to one store, at real network cost) yields a pile of per-service
snapshots lacking the contextual thread connecting one request's journey across
downstream dependencies. Distributed logging (leaving logs near where they are
produced, across clouds) trades that transport burden for scattered storage. Both
coexist with tracing; teams typically start with logs and add tracing as
architecture complexity grows. Traces are the third pillar alongside logs and
metrics, and the piece frames observability — exploring properties you did not
define in advance — as the successor to traditional predefined-dashboard
monitoring.

Claimed benefits: lower mean time to detect and repair, catching degradation before
users notice, SLA compliance, protecting revenue, faster shipping, and better
cross-team collaboration because fault localization is objective. The honest part
is the challenge list: some tools need manual code instrumentation (time-consuming,
error-prone, easy to leave gaps); some only start a trace at the first backend
service, severing the link to the frontend user session and making
backend-vs-frontend triage needlessly hard; and head-based sampling — randomly
deciding at request start whether to keep a trace — silently drops traces you later
wish you had, including high-value transactions. Tail-based sampling, deciding
after the full trace is known, lets you keep complete traces matching priority
criteria.

## Key patterns & decisions

- **Trace-ID propagation**: assign a unique identifier at the request's entry and
  thread it through every downstream call so the whole journey is reconstructable.
- **Span model with parent-child hierarchy**: record each operation as a timed,
  metadata-bearing span linked to its caller, so ordering and latency attribution
  fall out of the structure.
- **Tail-based over head-based sampling**: deferring the keep/drop decision until a
  trace completes preserves high-priority and anomalous traces that random up-front
  sampling loses.
- **Frontend-to-backend trace continuity**: start traces at the user session, not the
  first backend hop, or you cannot tell which side of the stack owns a slow request.
- **Traces complement, not replace, logs and metrics**: logs give component-local
  detail, metrics give aggregates, traces supply the cross-service request context
  the other two lack.
- **Fault localization as a collaboration tool**: objective per-service attribution
  of latency and errors replaces war-room blame with a pointer to the owning team.
- **Instrumentation cost awareness**: manual instrumentation is a real adoption tax
  and gap source; prefer automatic instrumentation or accept process discipline.
- **Centralized vs distributed log placement**: aggregate logs centrally for
  convenience at network/storage cost, or leave them local at query-complexity cost —
  an explicit trade, not a default.

## When to apply / trade-offs

- Tracing pays off once a single request crosses several services — microservices
  and serverless especially — and is the fastest route to root cause for latency and
  error triage; in a small monolith, logs plus metrics may still suffice.
- Sampling strategy matters at volume: full-fidelity capture of every trace is
  expensive in high-throughput systems, but naive head sampling defeats the purpose
  precisely for the requests you care most about.
- Watch scope gaps: backend-only tracing and uninstrumented components create blind
  spots that reintroduce the very ambiguity tracing exists to remove.
- Source is vendor marketing — the mechanics and challenge taxonomy are sound and
  vendor-neutral (they map directly onto OpenTelemetry concepts), but "advanced
  solution" framing is a pitch; evaluate against open standards first.

## Fidelity check

1. *Claim:* a trace is a hierarchy of spans, each a timed unit of work with metadata.
   *Support:* the capture describes every activity triggered by a request being
   recorded with a name, start and end timestamps, and other metadata, with completed
   parent spans handing off to child spans and the trace ordering them; its FAQ
   restates spans as operations like API calls or DB queries linked parent-to-child
   under one trace ID.
2. *Claim:* head-based sampling risks losing exactly the traces you value; tail-based
   fixes this. *Support:* the capture explains that sampling randomly at request
   start leaves some traces missing or incomplete so high-value transactions cannot
   be reliably captured, and contrasts this with tail-based decisions that keep
   complete traces tagged with priority characteristics.
3. *Claim:* log aggregation alone cannot reconstruct a request's cross-service path.
   *Support:* the capture states aggregated logs offer a snapshot of individual
   services but lack the contextual metadata to follow a request downstream through
   its dependencies, which is why tracing is needed in distributed environments; it
   also notes centralized log transport can itself strain network resources.
