---
source: https://algomaster.io/learn/system-design/pub-sub
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Publish-Subscribe: decoupled event fan-out with per-subscription responsibility

## What it teaches

The chapter motivates pub/sub with the checkout scenario: one placed order should trigger
inventory, notifications, analytics, fraud checks, and shipping, yet the order service must not
synchronously chain-call all of them — that couples latency and availability of the whole checkout
path to its slowest downstream. Pub/sub inverts the dependency: a publisher emits a fact to a
named topic, and any number of subscriptions attached to that topic each get an independent copy.
The critical structural insight is that the *subscription*, not the topic, is the unit of delivery
state — each subscription tracks its own acknowledgments, backlog, retry policy, filters, and
dead-letter routing, so one slow or dead consumer never stalls the others.

## Key patterns & decisions

- **Queue vs pub/sub intent split**: a work queue means "somebody should do this task once"
  (competing workers), pub/sub means "this fact occurred" (every interested party gets a copy).
- **Publish facts, not instructions**: events describe what happened; encoding per-consumer
  directives into an event forces the publisher to know its consumers, defeating the pattern.
- **Subscription as the isolation boundary**: per-subscription ack tracking, retries, filters,
  and DLQs are what make consumers fail independently.
- **Attribute-level filtering over payload parsing**: filter at the broker on message attributes
  so consumers do not deserialize whole messages just to discard them.
- **Push vs pull delivery choice**: push suits webhook-style endpoints but the broker sets the
  pace; pull lets the consumer control batch size, worker count, and rate.
- **Consumer groups within a subscription**: fan-out (copy per subscription) is orthogonal to
  load-balancing (one subscription's messages shared across worker instances).
- **Durability tiers**: ephemeral delivery (only currently-connected subscribers) for presence
  and cache-invalidation signals; durable subscriptions for business events; replayable logs
  for pipelines and reprocessing — and replay demands idempotent consumers.
- **Key-scoped ordering, not global**: expect ordering only per partition/ordering-key/entity;
  route related events by entity ID and carry eventId/version so consumers can drop stale updates.
- **At-least-once implies idempotency + DLQ**: distinguish transient from permanent failures,
  back off on retries, dead-letter repeat offenders, and alert on backlog growth.
- **Events are contracts**: additive-only schema evolution, versioning, ownership, optional
  schema registry; never publish raw database rows as public events.
- **Fan-out-to-queues topology** (e.g. topic feeding per-consumer queues): combines broadcast
  with per-subscriber buffering and independent worker scaling.
- **Pub/sub is not event sourcing**: distributing events over a broker does not make the event
  log the source of truth; most systems keep state in normal databases.

## When to apply / trade-offs

Apply when multiple services must react to the same fact, the publisher should stay ignorant of
its consumers, eventual (slightly delayed) updates are acceptable, and new consumers will keep
appearing. Avoid it when the caller needs an immediate answer, there is exactly one handler,
the workflow needs strict step sequencing (a workflow engine is clearer than an event chain),
consumers cannot tolerate duplicates or reordering, or nobody owns backlog monitoring. The
pattern relocates failure handling into every subscriber rather than eliminating it.

## Fidelity check

1. Claim: delivery state lives on the subscription, not the topic. Support: the capture states
   each subscription attached to a topic separately tracks what has been acknowledged, what is
   pending, its filters, its retry behavior, and where failed messages land.
2. Claim: durable pub/sub is normally at-least-once, so consumers must be retry-safe. Support:
   the delivery-failures section says most durable systems can hand a subscriber the same event
   more than once and prescribes idempotent handling, backoff, DLQs after a retry limit, and
   backlog alerts.
3. Claim: ordering guarantees are scoped to a key/partition, and the fix is entity-keyed routing
   plus version fields. Support: the ordering section says brokers only order within a partition,
   message group, or ordering key, and advises keying related events by orderId/accountId and
   carrying eventId/eventTime/version so consumers can ignore superseded events.
