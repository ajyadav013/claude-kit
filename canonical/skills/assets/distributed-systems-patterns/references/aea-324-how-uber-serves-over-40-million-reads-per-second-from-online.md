---
source: https://www.uber.com/en-IN/blog/how-uber-serves-over-40-million-reads-per-second-using-an-integrated-cache/
author: Uber Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# CacheFront: moving caching from every team's app code into the database's own query layer

## What it teaches

Uber's Docstore (a sharded, Raft-replicated document store over MySQL) hit a
wall where read-heavy customers would have needed cost-prohibitive vertical or
horizontal scaling. Teams were each bolting their own Redis cache-aside layer
onto services, duplicating invalidation logic and failover handling. The
article describes CacheFront: a Redis caching tier integrated *inside*
Docstore's stateless query-engine layer, so every client gets transparent
caching through the existing API, with invalidation, warming, sharding, and
failure handling owned once by the database team.

The design's center of gravity is invalidation. TTL alone was too slow;
write-path invalidation cannot handle conditional updates (you don't know
which rows matched a filter until the storage engine applies it); so they
drive invalidation from the MySQL binlog via their CDC service, and add a
per-row-version deduplication script in Redis to prevent racing writers from
regressing the cache to a stale value.

## Key patterns & decisions

- **Cache integrated at the query-engine layer**: put caching inside the
  database's stateless routing tier rather than in each application; it stays
  transparent behind existing client APIs and scales independently of storage.
- **Opt-in, per-request consistency granularity**: caching can be enabled per
  database, table, or request, so strongly consistent flows (a cart read)
  bypass the cache while read-heavy tolerant flows (a menu) use it.
- **CDC/binlog-driven invalidation**: tail committed change events to
  invalidate or upsert cached rows — handles conditional updates, converges
  the cache within seconds instead of TTL minutes, and, because binlog events
  are committed, uncommitted transactions can never pollute the cache.
- **Row-version dedup via an atomic server-side script**: writes into Redis
  compare the row's database timestamp/version and only overwrite older
  entries, resolving the race between read-path population and CDC-path
  updates in one round trip.
- **Explicit invalidation API for read-your-writes**: point-write callers who
  need stronger-than-eventual semantics can invalidate affected keys
  themselves after the write completes.
- **Shadow-compare mode to measure consistency**: mirror a slice of reads to
  both cache and database, diff results, and emit mismatch metrics — the
  claimed 99.99% cache consistency is measured, not assumed.
- **Key-replication cache warming across regions**: replicate cache *keys*
  (not values) to the standby region, where a consumer issues reads through
  the local query engine on miss; the cache warms from the region-local
  database, avoiding a second value-replication path that could diverge.
- **Negative caching**: record queried-but-absent rows under a special
  marker so repeated misses for nonexistent data stop hitting the database.
- **Cross-sharded cache and store**: shard Redis by partition key on a
  different scheme than the database's sharding, so losing one Redis cluster
  spreads its miss traffic across all database shards instead of hammering
  one.
- **Sliding-window circuit breakers per cache node**: short-circuit a
  fraction of requests proportional to recent error counts on a node, rather
  than paying guaranteed-to-fail latency.
- **Adaptive timeouts**: dynamically set the cache-op timeout near the
  observed P99.99 latency instead of hand-tuning static values, so slow
  outliers fail over to the database quickly without starving normal hits.

## When to apply / trade-offs

- The pattern fits platform teams serving many internal customers: the win is
  as much organizational (one owned cache instead of N team-built ones) as
  technical.
- CDC-based invalidation is the key enabler but presumes you have a reliable
  change-capture pipeline; without it you are stuck choosing between TTL
  staleness and write-path invalidation that breaks on filter-based updates.
- Cache warming by key replication trades a little extra read traffic on
  miss for the guarantee that each region's cache content is derived only
  from that region's database — a subtle divergence-avoidance decision.
- Reported results: P75 latency down ~75%, P99.9 down >67% with spike
  smoothing; one use case served ~6M RPS at 99% hit rate on ~3K Redis cores
  versus an estimated ~60K CPU cores if served from storage; >40M RPS total
  across production.
- Failure-isolation choices (independent cache/store sharding, circuit
  breakers, adaptive timeouts) all address the same risk: the cache must
  never turn its own failure into a database overload.

## Fidelity check

1. Claim: conditional updates force CDC-based invalidation. Support: the
   capture states the query layer cannot know which rows a filter-based
   update will touch until the storage engine applies it, so a consumer of
   the binlog-tailing service (Flux) invalidates or upserts affected rows.
2. Claim: a version-checking atomic script prevents stale overwrites.
   Support: the capture describes deduplicating concurrent cache writes using
   the MySQL row timestamp as a version, executed atomically in Redis via a
   custom server-side script so the check-and-set happens in one request.
3. Claim: region warming replicates keys, not values. Support: the capture
   explains that tailing the Redis write stream and shipping only keys to
   the remote region — which then populates itself through its own query
   engine on miss — keeps the cache consistent with the local database and
   limits cross-region bandwidth.
