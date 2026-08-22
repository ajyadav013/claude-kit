---
source: https://algomaster.io/learn/system-design/webhooks
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Webhooks: building a receiver that survives duplicates, reordering, and attackers

## What it teaches

How to consume push notifications from an external system (payments, GitHub,
CI, AI-job platforms) without corrupting local state. The framing insight is
that a webhook is just an HTTP request crossing the internet — it can be late,
duplicated, reordered, forged, or lost — so every design decision flows from
assuming those failure modes rather than hoping the provider is well-behaved.
The chapter covers the register→event→deliver→acknowledge lifecycle, the shape
of a hardened receiver, and the production pipeline (queue, workers, event
store, DLQ, reconciliation) that separates receiving from processing.

## Key patterns & decisions

- **Thin acknowledge path**: the HTTP handler does only signature verification,
  basic validation, durable save/enqueue, then returns 2xx; all business work
  runs in background workers so provider timeouts and retries stay rare.
- **HMAC verification over the raw body**: compute the signature from the exact
  bytes received (not re-serialized JSON), compare in constant time, honor the
  provider's timestamp to reject replays, and plan for secret rotation. Real
  providers use their own header formats, so build per-provider endpoints
  rather than one generic route.
- **At-least-once mindset with durable dedupe**: keep a processed-event record
  keyed by provider event/delivery ID under a unique constraint; a duplicate
  that was already accepted gets a success response without re-running effects.
  This makes redelivery safe — it does not create exactly-once delivery.
- **Never trust delivery order**: retries reorder events, so handlers should
  fetch current resource state from the provider before critical transitions,
  use version/timestamp fields when available, and model state changes so an
  invalid backward step is rejected rather than silently applied.
- **Status codes as a retry contract**: 2xx only after the event is durably
  saved (a crash after a premature 200 loses the event forever); 4xx for
  malformed/unauthorized requests; 429/5xx for conditions the provider should
  retry.
- **Outbox or single-write boundary**: saving the event to the database and
  pushing to a separate queue as two independent writes is a dual-write bug —
  either commit both in one transaction via an outbox table with a relay, or
  let workers poll the events table directly.
- **Event store for audit and replay**: persist provider, event/delivery IDs,
  needed headers, (possibly redacted) body, verification result, and status
  timestamps so operators can answer "did we get it, did we queue it, who
  processed it, can we replay it."
- **Classified retries plus DLQ**: retry transient failures with backoff and
  jitter under a max-attempt cap; do not retry permanently-malformed events;
  park exhausted events in a dead-letter queue rich enough to debug and replay
  after the fix.
- **Reconciliation as the safety net**: webhooks are treated as "something
  changed" signals; a periodic polling job compares local state with provider
  state to catch missed or inconsistent events — webhooks and polling are
  complements, not rivals.
- **Defense-in-depth on a public endpoint**: signatures are the primary
  control; IP allow lists are optional noise reduction only; never leak
  secrets, stack traces, or unredacted payment/personal data into logs or
  responses.

## When to apply / trade-offs

Use webhooks when another system owns the event, you need to react quickly,
polling would be wasteful, and you can operate a reliable endpoint that
tolerates duplicates and delays. Avoid webhook-only designs when strict
ordering is required, the receiver is unreliable, the consumer must control
its own processing rate, or there is no replay/reconciliation path for
critical events. The cost of doing it right is real infrastructure — event
store, queue/outbox, workers, DLQ, metrics (queue depth, oldest-event age,
signature-failure spikes, zero-event alarms) — but skipping it produces the
classic silent failures: orders stuck pending, jobs never marked complete.

## Fidelity check

1. *Claim: returning 200 before durably saving the event can lose it
   permanently.* The capture warns that if the process crashes after
   responding with success but before persisting, the provider believes
   delivery succeeded and will never retry.
2. *Claim: signature checks must run on raw bytes with constant-time
   comparison.* The verification section says to sign/verify the raw request
   body rather than parsed-and-reprinted JSON, and to use constant-time
   comparison so timing differences do not leak the secret.
3. *Claim: save-then-enqueue as two separate writes is a dual-write hazard.*
   The scalable-infrastructure section states that independent database and
   queue writes can drop or double-process an event if the process crashes
   between them, and prescribes an outbox-with-relay or workers polling the
   events table.
