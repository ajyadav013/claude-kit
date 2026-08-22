---
source: https://engineering.razorpay.com/how-razorpays-notification-service-handles-increasing-load-f787623a490f
author: Razorpay Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Keeping a webhook delivery service inside SLA as load grows

## What it teaches

Razorpay's notification platform (SMS, email, and above all webhooks) started
degrading past ~1K TPS: p99 latency doubled, and the database — not the
workers — was the ceiling. Rather than rebuild for some fixed target load, the
team applied four containment moves: prioritize traffic, decouple DB writes,
penalize slow receivers, and instrument everything. The closing thesis: when a
problem is too big to solve outright, shrink it.

## Key patterns & decisions

- **Criticality-tiered queues.** Not all notifications matter equally, and one
  type must not starve another. Traffic is split into a small exclusive
  top-priority queue for business-critical events, a default queue for
  everything else, and a dedicated queue for burst events (very high TPS over
  a short window). Isolation limits the blast radius of any one event type.
- **Per-event rate limits with an overflow queue.** Each event type gets a
  quota (higher on the priority tier); an event breaching its quota is diverted
  to a separate rate-limit queue instead of degrading its neighbors. Limits are
  tunable per consumer and per observed load pattern. The team credits this
  combination with DoS resistance and genuine multi-tenancy.
- **Autoscaling workers vs. fixed-IOPS database is a trap.** Worker pods scaled
  horizontally with load, but every added pod raised database IOPS until the DB
  itself throttled the whole system; repeatedly doubling the instance size was
  a dead end.
- **Buffer DB writes through a stream.** Workers stopped writing results
  directly to the database and instead publish idempotent messages onto a
  stream (Kinesis); a dedicated writer drains it at a controlled rate. Write
  throughput to the DB stays constant regardless of ingest spikes, workers can
  scale freely, audit-writing and data-lake export separate cleanly from
  delivery, and the retry queue no longer contends with the main queue.
- **QoS demotion for slow endpoints.** Webhook delivery blocks a worker until
  the receiver responds, so a few slow customer servers could drag the whole
  service. If a customer's response time crosses a threshold, their events are
  deprioritized for a cooling-off window, then re-probed. Alerts can notify the
  customer's own stakeholders that their endpoint is degrading.
- **Observability across all three pillars to shrink MTTD/MTTR.** Dashboards
  and alerts for anomalies (rogue events, rate-limited events, slow customers,
  success rate), log-derived error-pattern dashboards, and distributed tracing
  across components.
- **Shrink the problem before re-architecting.** None of the four moves was a
  breaking change; together they reduced pressure enough to buy time for
  longer-term design.

## When to apply / trade-offs

- The stream-buffered write pattern fits any pipeline where downstream
  persistence has a hard throughput ceiling but ingest bursts; it trades write
  latency (results land in the DB asynchronously) for stable DB health, and it
  requires idempotent messages since stream delivery can duplicate.
- Priority queues + per-event rate limits are the queueing form of the bulkhead
  pattern — worth adopting anywhere multiple tenants or event classes share
  one delivery pipeline.
- QoS demotion punishes the misbehaving party instead of the whole tenant
  population, but needs care in latency-sensitive domains (a deprioritized
  payment webhook still has an SLA) and a fair re-promotion probe.
- Burst days are predictable in fintech (quarter close, festival sales, cricket
  season); capacity planning should treat them as first-class inputs, not
  anomalies.

## Fidelity check

1. Claim: the database, not compute, was the scaling ceiling. Support: the
   capture says worker pods could scale arbitrarily but DB IOPS limits meant
   more pods degraded the database, and the stopgap was repeatedly doubling
   instance size (2x.large → 4x.large → 8x.large) until that stopped helping.
2. Claim: messages on the stream are idempotent and the writer controls DB
   write rate. Support: the capture describes the stream inserted between
   workers and the DB, notes all messages pushed to Kinesis are idempotent,
   and says this gave control over the DB write rate so IOPS could be
   throttled while load stayed high.
3. Claim: slow customer servers trigger temporary priority demotion. Support:
   the capture describes a QoS rule where response times beyond a limit
   (example given: five minutes) lower that customer's event priority for the
   following minutes, with a later re-check of the endpoint's health.
