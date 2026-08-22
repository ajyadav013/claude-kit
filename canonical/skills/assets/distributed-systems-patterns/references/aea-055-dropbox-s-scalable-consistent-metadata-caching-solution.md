---
source: https://dropbox.tech/infrastructure/meet-chrono-our-scalable-consistent-metadata-caching-solution
author: Dropbox
license-note: ideas absorbed in own words; no text or code reproduced
---

# Chrono: read-after-write caching by tracking write-attempt timestamps, not values

## What it teaches
How Dropbox added a cache in front of its MVCC metadata store (Panda)
without breaking the read-after-write guarantee hundreds of internal client
teams silently depend on. The core insight: don't try to keep cached values
consistent — keep a tiny, monotonic "latest write attempt" timestamp per key
in a separate service (Chrono), and let a plain lossy cache (Memcache) hold
values tagged with the storage read-timestamp they were observed at. A
cached value is served only if its read timestamp is at least the latest
attempt timestamp; every write must first register a future-bounded attempt
timestamp that also caps the storage commit timestamp. Staleness then
becomes logically impossible, provable by contradiction, and the design was
checked with TLA+ plus continuous self-verifying workloads.

## Key patterns & decisions
- **Why naive caching fails** — write-through can strand stale entries if
  the writer crashes between store and cache; even invalidate-before-write
  loses to a race where a reader that read the old value repopulates the
  cache after a later reader cached the new one.
- **Announce-before-write (intent registration)** — a writer must first tell
  Chrono an attempt timestamp for the key; that same timestamp is passed to
  storage as a maximum permitted commit timestamp, so no commit can ever
  exceed what Chrono knows about. This is the fencing that makes the proof
  work.
- **Timestamp service separated from value cache** — Chrono stores only
  key → highest-attempt-timestamp; values live in ordinary Memcache/Redis
  that may be lossy or stale with no correctness impact. Each side scales
  independently.
- **Freshness check instead of invalidation** — read path queries Chrono and
  Memcache in parallel; serve the cached value only when its read timestamp
  is not older than the latest attempt timestamp, otherwise fall through to
  storage's transactionally-consistent latest-read API and repopulate.
- **Clock skew affects liveness, never safety** — attempt timestamps are
  chosen slightly ahead of now (e.g. now + a few seconds) so writes succeed
  and caching windows stay short; arbitrary skew can only cause failed
  writes or extra cache misses, not stale reads.
- **Monotonicity across crashes via persisted upper bound** — Chrono
  periodically advances a durable ceiling timestamp and refuses attempts
  above it; after restart it never answers below the persisted bound, so
  its answers never regress.
- **Hash-bucketed timestamp table** — attempt timestamps are stored per hash
  slot rather than per key, trading false-positive staleness (aliasing) for
  strictly bounded memory.
- **Offloading reads to followers** — snapshot reads at a Chrono-supplied
  timestamp are safe to serve from storage replicas, shifting heavy read
  traffic off leaders even on cache miss.
- **Model-check the startup sequence, not just steady state** — a prior
  protocol version passed a steady-state-only TLA+ model; modeling the boot
  sequence exposed the invariant violation a human had spotted. Formal
  models are only as good as what you include.
- **Guarantees are a product decision** — the team's stated lesson: strong
  read-after-write semantics, once given away free, are nearly impossible to
  retract; avoid over-promising consistency to clients from day one.

## When to apply / trade-offs
Apply when read QPS outgrows a storage fleet but clients assume
read-after-write, and the storage layer offers MVCC commit timestamps plus
bounded-commit writes — the pattern is portable to any store with those
primitives. Costs: every write pays an extra round-trip to the timestamp
service; hash aliasing and conservative timestamps produce spurious misses
(never wrong answers); and the hardest engineering was reportedly not the
protocol but sharded-system operations — request bundling to cut fanout,
and hot-spot mitigation in both Chrono and the cache tier.

## Fidelity check
1. Claim: the commit timestamp can never exceed the registered attempt.
   Support: the capture's write API takes a maximum permitted commit
   timestamp and fails the write if storage would commit above it, and the
   protocol requires the Chrono attempt call to succeed before the write is
   issued.
2. Claim: correctness is argued by contradiction. Support: the capture
   proves that serving a stale cached value would require a newer committed
   write whose attempt timestamp Chrono must already have observed, which
   would have forced the freshness check to reject the cached entry.
3. Claim: TLA+ missed a real bug until startup was modeled. Support: the
   capture recounts an earlier flawed protocol iteration whose buggy boot
   sequence passed a steady-state-only model; human inspection found the
   bug, and adding the startup sequence to the model then reproduced the
   invariant violation quickly.
