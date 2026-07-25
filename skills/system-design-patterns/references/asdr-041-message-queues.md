---
source: https://algomaster.io/learn/system-design/message-queues
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Message queues: buffered background work, and the failure modes the buffer buys you

## What it teaches

A synchronous call ties the caller's latency and availability to the callee. A message queue
severs that link: producers deposit units of work with a broker; consumers pull and process them
later. The chapter is careful to frame the queue not as a pure performance win but as a
*behavioral* change to the system — work becomes deferred, deliveries can duplicate, ordering
becomes a deliberate design decision, and backlog depth becomes an operational signal someone
must own. The acknowledgment step is presented as the reliability keystone: the broker only
forgets a message once a consumer confirms completion, which is what makes crash recovery
possible — and what makes duplicate delivery inevitable.

## Key patterns & decisions

- **Ack-then-delete as the reliability contract**: consumer crash before ack means redelivery;
  therefore at-least-once is the working assumption and every consumer must be idempotent
  (idempotency keys, unique constraints, or processed-message ledgers).
- **Claim-check for large payloads**: keep messages small and versioned; park big blobs in
  object storage and enqueue only a reference.
- **Pattern taxonomy**: work queue (one consumer per task, horizontal worker scaling),
  pub/sub (copy per subscriber), priority queue (urgent jumps the line, at the cost of
  starving low-priority work), delayed/scheduled queue (retry-later, reminders, timeouts),
  dead-letter queue (quarantine after retry exhaustion so poison messages stop blocking the
  main flow and can be inspected/replayed).
- **Load leveling**: the queue absorbs bursts that exceed steady-state consumer throughput —
  valid only when delayed processing is acceptable to the product.
- **Independent scaling with a caveat**: producers and consumers scale separately, but adding
  workers is useless when the real bottleneck is a shared DB lock or third-party rate limit.
- **Backlog observability beyond depth**: queue depth alone misleads; also track oldest-message
  age, publish vs consume rates, retry rate, and consumer error rate.
- **Retry hygiene**: bounded retries with backoff and jitter, plus circuit-breaking, so a
  thousand aggressive retriers do not prolong a downstream outage.
- **Message format as a versioned contract**: additive-only changes, explicit ownership, no
  field removal/rename without a migration plan.
- **Queue governance**: every queue needs a named owner, documented purpose, retention policy,
  alerting, access control, encryption of sensitive payloads, and a tested replay plan.
- **Tool-to-workload matching**: broker-style systems (RabbitMQ, SQS, Service Bus) for task
  queues and routing vs a partitioned log (Kafka) for streams and replay — the common failure
  is picking the technology before characterizing the workload.

## When to apply / trade-offs

Use a queue for background jobs (email, media processing, reports), event-driven cross-service
reactions, burst absorption, and retrying against flaky dependencies. Skip it when the caller
needs a synchronous answer, validation must complete before responding, exact cross-entity
ordering is required, no one will watch the backlog, or a direct call is simply adequate. The
subtle hazard the chapter flags: a queue can *mask* failure — the API returns success because
enqueue succeeded, while the real work silently fails minutes later, so the product experience
must be designed around that gap.

## Fidelity check

1. Claim: acknowledgment is what enables crash recovery and simultaneously forces idempotent
   consumers. Support: the capture's flow ends with the consumer confirming success before the
   broker removes the message, and its trade-offs section says a message can be redelivered if
   the consumer crashes after doing the work but before acking.
2. Claim: monitoring should include oldest-message age, not just queue depth. Support: the
   failure-modes section states depth alone is insufficient and recommends also tracking how
   old the oldest message is and how far consumers lag.
3. Claim: dead-letter queues exist to keep poison messages from clogging the main queue while
   preserving them for inspection. Support: the DLQ section describes moving messages that
   exhausted retries to a separate location where engineers can examine, repair, replay, or
   discard them.
