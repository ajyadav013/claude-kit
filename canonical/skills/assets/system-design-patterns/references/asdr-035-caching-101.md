---
source: https://algomaster.io/learn/system-design/what-is-caching
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Caching fundamentals: layered fast copies, hit ratios, and the staleness tax

## What it teaches

A cache is a fast key-value layer holding copies of frequently read data so requests skip the
slower source (database, downstream service). The motivating example is a social feed load that
fans out into dozens of database queries — authentication, profile, follow list, posts, counts,
avatars — which at scale makes the database the bottleneck; caching the hot reads cuts latency
roughly an order of magnitude and buys database headroom and cost savings. The chapter's core
tension: a cache stores a *copy*, and every copy can drift from the truth, so caching design is
really staleness management. It maps the full cache hierarchy (browser via Cache-Control/ETag
headers, CDN edge nodes, in-process application memory, shared distributed caches like
Redis/Memcached, and the database's own buffer pool) and closes with anti-patterns and
distributed-cache failure policy.

## Key patterns & decisions

- **Layered cache hierarchy with distinct jobs**: browser (per-device, header-controlled),
  CDN (shared static/public content at the edge), in-process (fastest but per-instance and
  divergent), distributed (network hop but shared and large), DB buffer pool (automatic,
  invisible to app code).
- **Hit ratio as the primary effectiveness metric**: above ~95% excellent, 80-95% normal,
  under 50% signals an undersized cache or cache-unfriendly data; a 90% hit ratio multiplies
  effective read capacity roughly 10x for the covered reads.
- **Cacheability criteria**: read-many, expensive-to-compute, slow-source, rarely-changing
  data caches well; write-heavy, per-request-unique, oversized, or staleness-intolerant data
  does not.
- **Hot-set focus (80/20)**: roughly a fifth of the data serves most requests — cache that
  slice instead of everything; cold keys rarely repeat enough to justify memory.
- **Consistency strategy menu**: TTL expiry (simple, bounded staleness), explicit invalidation
  on change (fresher, harder to get right), write-through (fresh reads, slower writes), and
  deliberately accepted short staleness — chosen per feature (a 5-minute-stale product blurb
  is fine; a 5-second-stale account balance is not).
- **Named anti-patterns**: cache-everything (memory waste), infinite TTL (one missed delete
  means wrong data forever), cache-as-primary-store (eviction/restart destroys unbacked data),
  and the thundering herd — hot-key expiry stampeding the database, mitigated by per-key
  locking, early refresh, or background refresh.
- **Cache-outage policy decided in advance**: fail-open (bypass to the DB — only if the DB can
  take the raw load), fail-closed (error out when the cache is correctness-critical), or serve
  stale as a graceful fallback; the wrong choice converts a cache outage into a total outage.
- **Consistent hashing for partitioned caches**: limits key movement when nodes join or leave.
- **Operational metric set**: hit ratio, cache lookup latency, memory usage, eviction rate,
  and miss latency (the cost of falling through), with p50/p99 framing; hit-ratio drops or
  eviction spikes are early warnings of traffic shifts or undersizing.

## When to apply / trade-offs

Introduce caching when read amplification, source latency, or cost pressures dominate and the
feature tolerates bounded staleness; keep the consistency mechanism proportional to the data's
staleness budget. Do not cache volatile, unique-per-request, or correctness-critical-fresh data.
Before relying on a distributed cache, decide the failure mode explicitly and verify the
database can survive a cache outage if you choose fail-open. This is a fundamentals chapter —
it deliberately defers interaction patterns (cache-aside etc.) to the next chapter, so it pairs
with a patterns source rather than standing alone for implementation guidance.

## Fidelity check

1. Claim: a 90% hit ratio roughly 10x-es effective read throughput for the cached reads.
   Support: the capture computes that if the database sustains 10,000 QPS for those reads,
   a 90% hit ratio lets the system serve about 100,000 read requests per second.
2. Claim: the thundering-herd anti-pattern is hot-key expiry causing a simultaneous stampede
   to the database, fixed by locking or pre-refresh. Support: the anti-patterns section
   describes many requests hitting the database at once when a popular entry expires and lists
   per-key locking, early refresh before expiry, and background refresh as the common remedies.
3. Claim: cache-unavailability behavior is a three-way policy choice that must be made ahead
   of time. Support: the distributed-systems section tabulates fail-open (skip cache, hit DB),
   fail-closed (return error when cache is required for correctness), and graceful stale
   fallback, warning that the wrong mode can escalate a cache outage into a full outage.
