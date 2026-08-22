---
source: https://algomaster.io/learn/system-design/sharding
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Sharding as a Last-Resort Write/Storage Scaling Move

## What it teaches

Horizontal partitioning of rows across independent database nodes lets a
dataset grow past what any single machine can hold or write, but the chapter's
core argument is economic: sharding is among the costliest scaling decisions a
team can make, so it should follow — never precede — cheaper levers like
indexing, query tuning, caching, read replicas, and bigger hardware. Once you
do shard, one design choice dominates every downstream property: the shard
key. Everything else in the chapter (routing, cross-node queries, joins,
transactions, rebalancing, hotspots) is a consequence of that choice.

A working sharded system rests on three mechanisms: a key column that
determines placement, a mapping function or table from key to node, and a
router (in the app, a client library, a proxy, or the DB itself) that steers
each request. Requests that carry the key touch one node; requests that don't
degrade into fan-out ("scatter-gather") queries that hit every node, merge,
and re-sort — a cost that grows linearly with node count.

## Key patterns & decisions

- **Shard key selection from query patterns**: choose the key that keeps the
  application's dominant reads and writes on a single node, not merely one
  that distributes bytes evenly. High-cardinality per-entity IDs (e.g. a user
  ID) tend to work; timestamps concentrate all fresh writes on one node, and
  low-cardinality fields (country, status, plan tier) skew badly.
- **Three placement strategies with distinct failure modes**: hashing evenly
  spreads data but makes capacity changes move many keys unless you layer
  virtual buckets or consistent hashing on top; range mapping serves range
  scans naturally but breeds hot tail ranges; a directory/lookup service gives
  per-tenant mobility at the price of a new critical dependency that must be
  highly available and cache-safe.
- **Geo-placement as a sharding dimension**: locating each region's rows in
  that region cuts latency and satisfies data-residency law, while accepting
  that global queries and region-migrating users become special cases.
- **Scatter-gather avoidance via dedicated read models**: instead of fanning a
  global query across all nodes at request time, maintain a separate
  precomputed read store, search index, or analytics system for the global
  view.
- **Co-locate by shared key to preserve joins and transactions**: denormalize
  the shard key onto child tables (e.g. carry the owner ID on line items) so
  related rows land on the same node; keep business-critical transactions
  single-node, because multi-node commits demand distributed transactions or
  compensating application logic.
- **Rebalancing designed before the emergency**: dual-location routing during
  a copy, verification before cutover, virtual buckets / consistent hashing /
  directory moves to bound how much data shifts, and migration tooling built
  in advance.
- **Hot-shard remediation ladder**: dedicated nodes for oversized tenants, a
  secondary split key for celebrity entities, caching and write buffering to
  absorb load without relayout, range splitting for hot ranges — and a data
  model rethink if one entity still dominates.
- **Shard-map changes treated as production migrations**, with per-node
  size/QPS/latency/error monitoring as the standing observability baseline.

## When to apply / trade-offs

Apply only when a measured bottleneck — write throughput, total storage, hot
working set exceeding RAM, tenant isolation, or data residency — survives the
simpler remedies, and the workload has a natural key that keeps important
operations local. Reads alone rarely justify it; replicas and caches are
cheaper. The permanent taxes are routing infrastructure, degraded cross-node
joins and transactions, rebalancing operations, and the ever-present risk of
hotspots even under good hashing (user activity is never uniform).

## Fidelity check

1. *Claim: scatter-gather cost grows with the shard count.* The capture states
   that queries lacking the shard key may need to ask every shard and merge
   results, and that this gets worse as the number of shards grows.
2. *Claim: modulo hashing makes capacity changes expensive.* The capture says
   changing the shard count under simple modulo hashing can relocate a large
   fraction of keys, and names virtual shards and consistent hashing as the
   mitigations that bound data movement.
3. *Claim: co-locating child rows means duplicating the shard key.* The
   capture's example keeps orders and order items on one node by storing the
   user ID on the order-items table too, so both tables shard on the same key.
