---
source: https://www.linkedin.com/blog/engineering/data-management/upscaling-profile-datastore-while-reducing-costs
author: LinkedIn Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Scaling a read-heavy datastore with a source-of-truth-independent cache tier

## What it teaches

LinkedIn's profile store (Espresso, a document database) hit the ceiling where
simply adding storage nodes could no longer absorb yearly request doubling —
shared components of the database itself became the bottleneck. Because the
workload is over 99% reads, the team inserted a Couchbase-based distributed
cache *inside the storage tier* (behind the Espresso routers) rather than in
the application. The crucial twist: since the cache exists specifically to
offload the database, it is forbidden from falling back to the database when
it fails. That constraint forces the cache to be engineered with the rigor
normally reserved for a primary store: replicated, bootstrapped, health-
monitored, and kept convergent with the source of truth by ordered updates.
The result: ~99% hit rate, p99/p99.9 multi-get latency down roughly 60%, a
90% reduction in storage nodes, and about 10% annual cost savings even after
paying for the new cache infrastructure.

## Key patterns & decisions

- **Cache-for-upscaling must not fall back to the source of truth.** If the
  cache exists to absorb load the database cannot take, a fallback path would
  turn every cache incident into a database overload. Design the cache to
  survive on its own instead.
- **Three explicit cache design principles**: guaranteed resilience to cache-
  cluster failures, cached data available at all times (including datacenter
  failover), and a stated SLO for divergence between cache and database.
- **Circuit-breaking health monitor per router**: each router tracks the
  exception rate of every cache bucket it talks to and stops sending requests
  to unhealthy buckets, so a sick cache cannot pile up requests and take the
  router down with it.
- **Leader-plus-two-replicas with follower fallback and categorized retries**:
  reads go to the leader replica; on leader failure they go to a follower.
  Failures are bucketed (router-side, network, server-side) and only the
  plausibly-transient categories are retried on a different router.
- **Full-dataset caching with finite TTL plus periodic re-bootstrap**: the
  whole profile dataset is cached in every datacenter (feasible because p95
  payload < 24 KB). Records get a finite TTL so lost deletes eventually purge
  themselves, and a scheduled bootstrap job re-seeds the cache faster than the
  TTL expires, so valid records never go cold.
- **Logical-timestamp ordering + last-writer-wins + tombstones**: every commit
  in the database gets a monotonically ordered change number; all cache
  writers (router, change-capture updater, bootstrapper) compare these numbers
  and only ever replace a record with a newer one. Deletes are written as
  tombstone records carrying just the change number, not as hard deletes, so
  ordering survives.
- **Compare-and-swap for concurrent writers**: the cache's CAS primitive
  detects racing updates from multiple writers and triggers a retry, closing
  the remaining divergence window.
- **Hybrid cache tiers**: a tiny in-router hot-key cache (frequency-based
  eviction) in front of the big distributed cache; the router alone decides
  which tier — or the storage node — serves a request, steered by a
  per-request staleness-tolerance header set by the application.
- **Cache full documents, move projection and schema up-conversion to the
  application**: field-level projections would explode the cache key space, so
  the cache stores whole documents "as written" and the backend now applies
  projection and converts old schema versions to the latest. That required the
  backend to fetch schemas dynamically from a registry at runtime (canary
  instances may write with a newer schema than the rest of the fleet has
  loaded).
- **Offset the added deserialization cost with a faster reader**: a rewritten
  datum reader that skips an intermediate representation cut per-record
  deserialization latency by roughly a third, paying for the work that moved
  into the application.

## When to apply / trade-offs

- Fits read-dominated workloads (here >99% read) with smallish records where
  caching the entire dataset per region is affordable. Write-heavy workloads
  would stress the change-capture pipeline and the ordering machinery.
- You are trading strong freshness for scale: the cache is eventually
  consistent with the database via a nearline change stream, so the
  application must express its staleness tolerance explicitly per request.
- The "no fallback" stance means real engineering cost: replication,
  bootstrapping jobs, tombstones, CAS, health monitors. A convenience cache
  does not need this; an upscaling cache does.
- Moving projection/up-conversion into the application shifts CPU cost onto
  app fleets (LinkedIn budgeted a ~30% compute buffer) — net savings must be
  measured end to end, which is why the honest figure is ~10%, not 90%.

## Fidelity check

1. *Claim: the cache was introduced because node addition stopped working.*
   Capture states the profile Espresso cluster reached the point where core
   shared components strained under load and expanding hardware further would
   need major reengineering.
2. *Claim: deletes are handled as tombstones plus finite TTL to bound
   divergence.* Capture describes upserting tombstone records containing only
   the change number instead of hard deletes, and choosing a finite TTL so
   records from lost delete events (e.g., events aging out of Kafka retention
   during an outage) eventually purge.
3. *Claim: measured wins were ~99% hit rate, >60% tail-latency cut on
   multi-gets, 90% fewer storage nodes, ~10% annual cost savings.* Capture's
   tables report multi-get p99 down 60.73% and p99.9 down 63.66%, a 99% cache
   hit rate, a 90% storage-node reduction, and a conservative 10% yearly
   cost-to-serve estimate.
