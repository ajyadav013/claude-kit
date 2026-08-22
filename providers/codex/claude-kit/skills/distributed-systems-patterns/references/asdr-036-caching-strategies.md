---
source: https://algomaster.io/learn/system-design/caching-strategies
author: AlgoMaster.io (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Choosing a Read/Write Path Through a Cache: The Five Canonical Strategies

## What it teaches

Adding a cache is only half the design decision — the other half is deciding
how reads and writes flow through it. Two questions determine everything: on a
miss, which component is responsible for populating the cache (the app or the
cache layer itself), and on a write, which store gets updated first and at what
point the caller is told "done". The chapter walks the five standard answers —
cache-aside, read-through, write-through, write-around, and write-back — and
frames each as a distinct position on a speed / freshness / complexity /
failure-risk spectrum rather than a ranking.

## Key patterns & decisions

- **Cache-aside (lazy loading)**: the application owns all cache logic — check
  cache, fall back to the DB on miss, backfill, and delete the entry on write.
  The cache is a pure accelerator: if it dies, the system degrades to slower
  DB reads instead of failing. Cost: cache-management code spreads through the
  app, first reads are cold, and a forgotten delete produces stale entries.
- **Read-through**: miss-handling logic moves into the cache layer itself, so
  every service that reads through it gets one shared loading path instead of
  each reimplementing the fill logic. Trade: the cache layer must know how to
  talk to the backing store, and a broken loader breaks all readers.
- **Write-through**: writes go to the cache layer, which synchronously persists
  to the DB before acknowledging. Reads immediately after writes see fresh
  data. Hard invariant: *every* writer must route through the cache path — one
  service writing the DB directly silently reintroduces staleness.
- **Write-around**: writes bypass the cache entirely and hit the DB; the cache
  only fills on subsequent reads. Keeps rarely-read writes (bulk imports,
  event ingestion, append logs) from polluting the cache, but pre-existing
  cached copies of the written key go stale unless explicitly deleted.
- **Write-back (write-behind)**: acknowledge on the cache write, flush to the
  DB asynchronously. Lowest write latency and enables batching under write
  spikes, but the caller can believe data is durable when it is not — safe use
  requires a durable buffer (WAL / replicated queue) plus ordering, retry,
  dedup, and recovery machinery. Even Redis AOF with per-second fsync can lose
  about a second of writes.
- **Match strategy to workload shape**: read-heavy → cache-aside or
  read-through; read-after-write → write-through; write-heavy with cold writes
  → write-around; high-volume loss-tolerant writes (counters, metrics) →
  write-back; loss/staleness-intolerant data (payments, audit) → don't cache
  the write path at all.
- **Compose strategies per data class, not one globally**: e.g. cache-aside
  reads + write-around writes is a common pairing, with write-back reserved
  for a narrow low-risk hot path.

## When to apply / trade-offs

Use this taxonomy whenever a design adds a cache in front of a database: the
read/write ratio, tolerance for stale reads, tolerance for lost writes, and
where the team wants complexity to live (app code vs cache layer vs background
flush infrastructure) pick the strategy. Write-back is the standout risk case:
it converts a latency problem into a durability problem, so it must never
carry data whose loss is unacceptable. Write-through's all-writers-use-one-path
constraint is an organizational contract as much as a technical one.

## Fidelity check

1. *Claim*: cache-aside keeps the system alive when the cache fails. The
   capture states that in cache-aside the cache is a speed boost rather than
   required storage, and a cache outage means slower DB reads and heavier DB
   load, not an outage.
2. *Claim*: write-back can silently lose acknowledged writes. The capture
   warns that the caller may consider a write saved before it reaches the
   database, that a cache failure before the background flush loses that data,
   and that Redis AOF's common every-second fsync setting can still drop
   roughly one second of writes.
3. *Claim*: write-through requires all writers on the cache path. The capture
   states as an explicit rule that if any one service writes the database
   directly, the cache may keep serving the old value.
