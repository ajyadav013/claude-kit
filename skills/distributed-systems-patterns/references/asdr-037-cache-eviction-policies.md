---
source: https://blog.algomaster.io/p/7-cache-eviction-strategies
author: AlgoMaster.io (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Deciding What to Throw Away: Seven Cache Eviction Policies

## What it teaches

A cache is finite, so every cache design implicitly bets on which items are
least valuable to keep. This article surveys seven eviction approaches — LRU,
LFU, FIFO, random replacement, MRU, TTL, and a two-tier local+remote layout —
and for each explains the underlying prediction it makes about future access,
the bookkeeping it requires, and the workloads where its prediction breaks
down. The through-line: every policy is a heuristic forecast, and its overhead
(metadata, update cost) must be paid on every access, not just at eviction
time.

## Key patterns & decisions

- **LRU — recency as the predictor**: evict the entry untouched the longest,
  typically tracked with a hash map plus a doubly linked list so hits can
  reorder in O(1). Fits browsing/API-style traffic well, but the ordering
  metadata costs memory and update work, and it assumes the past predicts the
  future.
- **LFU — frequency as the predictor**: evict the entry with the lowest hit
  count, with a tie-break (LRU or FIFO) when counts collide. Excellent when a
  stable "hot set" exists; weak when popularity shifts, because historically
  popular but now-dead items linger. Counter maintenance is the priciest
  bookkeeping of the group.
- **FIFO — age as the predictor**: evict in insertion order, ignoring hits
  entirely. Nearly free to implement and fully deterministic, but it happily
  evicts an item that is still hot, so it is rarely the right default.
- **Random replacement — no predictor**: evict an arbitrary entry. Zero
  metadata, and surprisingly serviceable when access patterns are chaotic
  enough that no signal exists to exploit; poor when there is a stable working
  set it keeps randomly ejecting.
- **MRU — inverted recency**: evict the *most* recently used item, on the
  theory that the latest access was a one-shot need. Useful only for niche
  scan-like workloads; actively harmful under normal locality, and rarely seen
  in practice.
- **TTL — freshness over popularity**: give each entry an absolute expiry so
  staleness is bounded regardless of access pattern; expired entries are
  reaped lazily on access or by periodic sweep (the model Redis/Memcached
  expose per key). Downside: hot-but-expired items get evicted anyway, and a
  fixed lifespan cannot adapt to workload shifts.
- **Two-tier caching — layered eviction domains**: a per-process in-memory
  tier for the hottest data in front of a shared distributed tier
  (Redis/Memcached class), with misses cascading local → remote → source and
  backfill into both. Buys near-zero-latency hits plus shared capacity and a
  fallback tier, at the price of cross-tier consistency and synchronization
  headaches.
- **Pick the policy by the access distribution and the metadata budget**, not
  by defaulting to LRU: frequency-skewed → LFU, recency-skewed → LRU,
  freshness-bounded → TTL, no discernible pattern → random/FIFO for cheapness.

## When to apply / trade-offs

Reach for this catalogue when sizing any bounded cache — in-process maps,
Redis maxmemory policies, or CDN-adjacent layers. The central trade is
prediction quality vs bookkeeping cost: LRU/LFU buy better hit rates with
per-access metadata updates, FIFO/random buy simplicity with worse retention.
TTL is orthogonal (it bounds staleness, not capacity) and is usually combined
with a capacity policy rather than substituted for one. Two-tier layouts are a
topology decision layered on top of whichever per-tier policy is chosen, and
they import consistency problems in exchange for latency.

## Fidelity check

1. *Claim*: LFU needs a tie-breaking rule. The capture specifies that when
   several entries share the lowest frequency count, a secondary policy such
   as LRU or FIFO decides which one goes.
2. *Claim*: FIFO ignores hits when ordering evictions. The capture's worked
   example shows an access to a cached item leaving the queue order unchanged,
   and that item later being evicted purely for being oldest.
3. *Claim*: the two-tier pattern checks local first, then remote, then the
   source, populating both caches on the way back. The capture's workflow
   describes exactly this cascade — local miss falls to the remote cache, a
   second miss goes to the database, and the result is written into both
   tiers before returning to the client.
