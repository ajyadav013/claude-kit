---
source: https://netflixtechblog.com/introducing-netflix-timeseries-data-abstraction-layer-31552f6326f8
author: Netflix TechBlog
license-note: ideas absorbed in own words; no text or code reproduced
---

# A purpose-built abstraction for immutable temporal event data at petabyte scale

## What it teaches

Netflix built a service layer ("TimeSeries Abstraction") on top of its Key-Value
abstraction and Data Gateway platform for one narrow job: appending and querying
immutable event records (video-play events, traces, impressions) at roughly ten
million writes per second with double-digit-millisecond primary reads. It is
deliberately NOT a metrics/analytics TSDB — that job stays with their telemetry
system. The article walks through the data model (event item → event → time
series id → namespace), a five-endpoint API split by durability and consistency
needs, a two-store storage layer (Cassandra for durable primary data,
Elasticsearch for secondary search/aggregation, both hidden behind storage
contracts), and a control plane that makes every dataset behavior a per-namespace
configuration knob rather than a code path.

## Key patterns & decisions

- **Three-level temporal partitioning**: retention-sized "time slices" (one
  table each) → "time buckets" inside a slice for range-scan targeting →
  "event buckets" inside a time bucket to absorb write bursts on one series.
  Each level trades a little read amplification for hot-partition avoidance.
- **Retention by dropping whole tables, not per-row TTL**: expiring individual
  rows litters an LSM store with tombstones and makes retention hard to change
  later; dropping a whole time-slice table is instant, cheap, and retention
  becomes a single control-plane edit. Cost: data lingers slightly past its
  window.
- **Durable vs fire-and-forget write endpoints**: a synchronous write with a
  durability ack for correctness-sensitive callers, and a lossy enqueue-only
  variant for logging/tracing callers who prefer throughput.
- **Client-supplied idempotency keys baked into every mutation** (event time +
  event id + item key), which is the precondition that makes retry and request
  hedging safe.
- **SLO-driven hedging and partial returns**: each endpoint carries a latency
  target; if a response misses it, an identical competing request is issued,
  and latency-sensitive readers can opt to receive whatever ordered subset has
  arrived rather than time out.
- **Adaptive read fanout**: scatter-gather reads start at a fixed parallel
  bucket count, then the service observes whether the dataset is dense or
  sparse and tunes future fanout down (or up) to cut read amplification.
- **Bounded write window enables immutability optimizations**: an "accept
  limit" rejects events older than N hours, so a time range becomes provably
  immutable quickly and can then be compressed, cached, and re-compacted
  aggressively; the limit is temporarily raised for backfills.
- **In-memory write coalescing only where loss is tolerable**: short-lived
  per-instance queues smooth bursts into batched datastore writes, with batch
  sizes tuned per backend — but the queues are bypassed for use cases needing
  durability or read-after-write.
- **Control plane / data plane separation**: everything schema-consensus-shaped
  lives in the control stack so the data path stays highly available; namespace
  config (partition widths, consistency, retention, indexed fields) is data,
  not code.

## When to apply / trade-offs

Apply when a system ingests append-only event streams far larger than its query
working set: the moves are (1) partition by time so retention and immutability
fall out structurally, (2) split callers by their real durability/consistency
needs instead of giving everyone the strictest path, and (3) push per-dataset
tuning into declarative config resolved by a control plane. Trade-offs the
article is honest about: bucketing raises read amplification (mitigated by
parallel scatter-gather); table-drop retention over-retains slightly; in-memory
buffering loses events on instance crash; and provisioning from user "workload
desires" is best-effort, so the platform must support re-partitioning future
slices when the real traffic shape shows up in partition histograms.

## Fidelity check

1. Claim: the system explicitly disclaims being a general TSDB. Support: the
   capture carries a note saying metrics/histogram/near-real-time analytics
   cases belong to their Atlas telemetry system, and this layer targets only
   high-throughput immutable event storage.
2. Claim: retention works by dropping whole time-slice tables to dodge
   tombstones. Support: the storage section argues per-row TTL would flood
   Cassandra with tombstones that degrade range scans, while discrete slices
   can be dropped wholesale, at the cost of keeping data a bit longer.
3. Claim: a JVM GC change measurably cut tail latency. Support: the buffering
   section reports that moving to JDK 21 with ZGC reduced their tail latencies
   by 86% for the queue-based write path.
4. Claim: real-world scale is ~15M events/second. Support: the performance
   section states peak global processing near fifteen million events per second
   across all datasets at time of writing.
