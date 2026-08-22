---
source: https://algomaster.io/learn/system-design-interviews/design-notification-service
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Designing a multi-channel notification service: queue-decoupled channel processors

## What it teaches

How to build the delivery backbone that fans messages out over email, SMS, push,
and in-app channels at flash-sale scale (~250M notifications/day, ~17K/s peak
bursts). The architecture is a pipeline: an ingestion API validates requests,
consults a user-preference layer (opt-outs, per-channel choices, daily frequency
caps), optionally parks future sends with a scheduler, renders channel-specific
payloads from templates, and drops one message per channel onto dedicated queue
topics. Independent channel processors consume their own topic and talk to the
external providers (SES/SendGrid-class for email, Twilio-class for SMS, FCM/APNs
for push, WebSockets for in-app), with exponential-backoff retries and a dead
letter queue behind them.

## Key patterns & decisions

- **Queue between accept and deliver** — the ingestion service acknowledges fast
  and enqueues; delivery happens asynchronously, so traffic spikes are absorbed by
  the broker rather than by synchronous provider calls.
- **Topic-per-channel with dedicated processors** — one notification request
  becomes N channel-tailored messages, each on its own topic consumed by its own
  horizontally scalable processor, so a slow SMS provider cannot back up email.
- **Preference and rate-limit gate before send** — a separate user-preference
  service enforces opt-in/opt-out by notification category and daily caps on
  promotional traffic, keeping spam control and compliance out of the delivery
  path's business logic.
- **Scheduler as a time-partitioned store + poller** — future sends land in a table
  partitioned by scheduled time; a periodic sweep picks up only the next window's
  rows and feeds them into the same queue as immediate sends.
- **Template-driven per-channel rendering** — the same logical notification is
  formatted differently per channel (rich HTML email, length-limited SMS, compact
  push payload with action metadata, JSON for in-app).
- **Retry with exponential backoff, then DLQ** — transient provider failures are
  retried on a widening schedule; exhausted messages go to a dead letter queue for
  manual review/replay instead of being dropped or retried forever.
- **Delivery-status logging per attempt** — processors record provider
  acknowledgments and failures (bounces, dead device tokens, bad numbers) in a log
  table for auditing, metrics, and channel-level success/latency dashboards.
- **Mixed storage by data shape** — relational store for structured delivery logs
  and transactional state, NoSQL for high-volume preference data, blob storage for
  large attachments; old logs move to cheap archival tiers on a time-based
  partition schedule.
- **At-least-once as the default guarantee** — the queue is configured for
  at-least-once delivery (duplicates possible, losses not), with exactly-once
  semantics reserved for the cases that justify the cost.

## When to apply / trade-offs

This is the canonical shape for any outbound-messaging subsystem: alerting,
transactional email, marketing campaigns, webhook dispatch. Reach for the
queue-decoupled processor pattern the moment delivery involves third-party
providers with independent failure modes and rate limits. Trade-offs to weigh:
at-least-once means downstream consumers (and users) may see duplicates unless
you add idempotency keys; per-channel topics multiply operational surface but buy
isolation; a polling scheduler is simple but bounds scheduling precision to the
sweep interval. The capture is shallower than sibling chapters — it lists
components and steps but skips deeper dives (no idempotency-key treatment, no
provider failover strategy, no per-provider rate limiting), so treat it as a
solid skeleton rather than a complete reference.

## Fidelity check

1. *Claim:* the queue is the scaling hinge between ingestion and delivery.
   *Support:* the capture describes the notification queue as a buffer decoupling
   request submission from delivery, credited with letting the system ride out
   high-traffic periods like flash sales.
2. *Claim:* each channel gets its own topic and consumer. *Support:* the detailed
   design walks through a request needing email, SMS, and push producing three
   distinct messages placed on an email topic, an SMS topic, and a push topic, each
   pulled only by its matching processor.
3. *Claim:* failed sends escalate from backoff retries to a dead letter queue.
   *Support:* the follow-ups section says transient failures (such as provider
   downtime) are retried with progressively longer delays, and messages still
   undelivered after the retry budget move to a DLQ where administrators can
   inspect and reprocess them.
