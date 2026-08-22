---
source: https://blog.algomaster.io/p/system-design-how-to-scale-a-database
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# An Eight-Rung Ladder for Scaling a Relational Database

## What it teaches

A survey of eight techniques for keeping a growing database from becoming the
application bottleneck, implicitly ordered from cheap-and-local to
expensive-and-distributed. The unifying lesson is that each rung trades a
different currency — money, write overhead, redundancy, staleness, or
operational complexity — and real systems combine several rather than picking
one. The eight: bigger hardware, indexes, sharding, column-wise table splits,
caching, replication, precomputed query results, and deliberate
denormalization.

## Key patterns & decisions

- **Vertical scaling as the first, bounded move**: adding CPU/RAM/storage to
  one server is fast and simple, but cost curves steepen, a hard ceiling
  exists, and the single machine remains a single point of failure.
- **Index the hot columns, not everything**: indexes accelerate lookups on
  frequently queried columns the way a book index avoids a page-by-page scan,
  but every extra index taxes writes, so over-indexing degrades insert/update
  throughput.
- **Horizontal sharding for data volume**: splitting rows across servers when
  one machine can no longer hold or serve the dataset (covered in depth in a
  companion piece).
- **Vertical partitioning by column access frequency**: split a wide table
  into narrower tables grouped by how often columns are read — e.g. a lean
  core-attributes table, a rarely-read details table, and a heavy-media
  table — so common queries scan less data.
- **Cache the skewed head of the access distribution**: most workloads have a
  hot subset (popular articles, active users, trending titles); serving it
  from a faster tier cuts latency and shields the database.
- **Replication for read locality and availability**: maintain synchronized
  copies in other regions so reads are served nearby; synchronous mode gives
  consistency at a per-transaction performance cost, asynchronous mode gives
  speed at the cost of a replication-lag staleness window.
- **Materialized views for expensive repeated queries**: physically store the
  result of a costly aggregation (unlike ordinary virtual views) and refresh
  it on a schedule — e.g. a nightly-refreshed daily sales rollup that
  management dashboards read instantly.
- **Denormalization to eliminate join cost**: intentionally introduce
  redundancy — folding child records into the parent (the article's example
  embeds a user's posts and comments as JSON on the profile row) — accepting
  update anomalies in exchange for single-fetch reads.

## When to apply / trade-offs

Treat the list as an escalation path: exhaust indexing, caching, vertical
scaling, and partitioning before reaching for sharding or denormalization,
which permanently complicate writes and consistency. Replication and
materialized views both trade freshness for speed (lag windows, refresh
intervals); denormalization trades write correctness effort for read
performance; indexes trade write throughput for read throughput. The right
blend is workload-specific — the article explicitly declines to crown a
universal winner.

## Fidelity check

1. *Claim: over-indexing hurts writes.* The capture notes indexes are built on
   the most-queried columns to speed reads, but adding too many slows write
   performance because of the maintenance overhead each index adds.
2. *Claim: vertical scaling concentrates risk.* The capture states that beyond
   expense and a scaling ceiling, putting everything on one bigger server
   creates a single point of failure.
3. *Claim: materialized views differ from ordinary views by physical
   storage.* The capture contrasts regular views, computed on the fly, with
   materialized views that persist precomputed results on disk for fast
   retrieval, illustrated by a scheduled-refresh daily sales summary.

## Notes

Newsletter listicle with paid-subscription upsells interleaved; the SQL
snippets in the source (materialized view DDL, normalized/denormalized
schemas) were treated as source code and described in prose only. Overlaps
heavily with the standalone sharding chapter (asdr-029), which it links to.
