---
source: https://innovation.ebayinc.com/stories/ebays-notification-streaming-platform-how-ebay-handles-real-time-push-notifications-at-scale/
author: eBay Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Broadcast fan-out in a microservice event platform without adopting a stream processor

## What it teaches
eBay's notification platform lets external partners subscribe to business events
(feed updates, bid changes, shipments) and receive HTTP push callbacks. Unicast is
easy; the hard case is broadcast — one event that must fan out to ~20,000
subscribers in real time. Loading every subscription in one shot blocks the
processing thread, breaches consumer timeouts, and wrecks latency. The team's
answer is a study in decomposing one long-running task into distributable,
re-runnable subtasks while staying inside their plain microservices stack.

They explicitly weighed adopting Flink/Spark and declined: the work is stateless
enrichment via blocking service calls, not stateful stream computation, and leaving
the mature in-house microservice ecosystem (CI/CD, monitoring, framework
management) would cost more than it bought. Crucially, they note the fan-out
decomposition problem exists regardless of engine — switching frameworks would not
have made it go away.

## Key patterns & decisions
- **Reconstructable partitioning on an immutable, ordered key**: subscriptions carry
  a creation timestamp that never changes and arrives in order, so sorting by it
  and grouping into fixed-size windows yields partitions any worker can cheaply
  re-derive later. Hash- or page-based splits were rejected because rebuilding,
  say, page 200 requires re-sorting and iterating the whole set.
- **Materialized view of partition boundaries**: computing all time windows on
  demand is still linear in subscriber count, so the windows are precomputed in a
  view refreshed on subscription insert — only the final window ever changes, and
  fetching the window list becomes constant-time. The pattern is portable: a plain
  table or in-memory grid works where the database lacks native materialized views.
- **Two-phase broadcast**: the receiving instance only splits the event into
  window-tagged subtasks, publishes them transactionally to a task queue, and acks
  the broker; cluster peers consume subtasks, fetch just their window's
  subscriptions, and push the notifications. This eliminated their message
  consumption timeouts.
- **Reactive Streams over hand-rolled concurrency**: the per-instance pipeline is
  built from reactive operators (parallel transforms, fan-in/fan-out, windowing,
  buffering) with a reactive queue connector, giving end-to-end non-blocking
  processing with backpressure-based flow control — chosen after also prototyping
  on the raw Java concurrency toolkit. Thread pools alone plateau at core count, so
  scale-out goes through the queue, not bigger pools.
- **Task affinity for cache locality**: routing subtask *i* to partition
  `i mod partition_count` binds each immutable window to a fixed consumer instance,
  so per-window subscription data and enrichment-call results stay hot in local
  memory instead of round-robining away the reuse.
- **Cache-stampede guard**: parallel operators can all miss the same key at once
  and stampede the backing service; an async cache that stores a future on first
  request (as Caffeine's AsyncCache does) makes concurrent readers await one
  in-flight load.

## When to apply / trade-offs
- The decomposition recipe — immutable ordered key, fixed windows, precomputed
  boundary view, queue-distributed subtasks — fits any "one trigger, N independent
  units of work" fan-out (bulk email, cache invalidation broadcasts, per-tenant
  jobs), especially where subtasks may need reprocessing.
- Choosing the microservice ecosystem over a dedicated stream engine is the right
  call when processing is stateless enrichment and the org's platform maturity is
  on the microservice side; revisit if genuinely stateful computation appears.
- Task affinity trades balanced load for cache hits and adds a rebalancing wrinkle
  when partition counts change; it pays off only because windows are immutable and
  per-window data is small.
- Fire-and-forget queue distribution assumes subtask idempotency or tolerance of
  redelivery — which the reconstructable windows are precisely designed to support.

## Fidelity check
1. Claim: the broadcast requirement was ~20,000 subscribers pushed in real time,
   and bulk-loading them blocked processing. Capture support: the article gives
   20,000 as the broadcast subscriber count and says fetching and processing all
   subscriptions in one task blocked the event-processing thread and raised
   latency, and elsewhere that the optimization removed consumption timeouts.
2. Claim: creation-timestamp windows were chosen because they are cheap to
   reconstruct, unlike pagination. Capture support: the text explains page-index
   reconstruction requires sorting and iterating the full dataset on their
   database, while the immutable, chronologically ordered creation timestamp
   yields stable groups and derived time windows suited to redistribution and
   reprocessing.
3. Claim: they declined Flink/Spark partly because the workload is stateless
   enrichment and the internal microservice ecosystem was too valuable to leave.
   Capture support: the considerations list says the processing is not stateful
   computation but enrichment through blocking service calls, that eBay's
   microservice ecosystem (CI/CD, monitoring, framework management) is mature, and
   that the task-decomposition problem would persist on any streaming system.
