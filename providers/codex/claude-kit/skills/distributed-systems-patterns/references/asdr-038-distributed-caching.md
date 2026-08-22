---
source: https://blog.algomaster.io/p/distributed-caching
author: AlgoMaster.io (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Scaling the Cache Layer Beyond One Node: Distributed Caching

## What it teaches

A single cache server stops being enough once the working set and traffic
outgrow one machine's RAM and network capacity; the answer is to spread cache
data over a cluster of nodes. The article covers why you distribute (capacity,
fault isolation, load spreading), the moving parts of a distributed cache
(client library, hashing, sharding, replication, eviction, coordination), the
placement decision between dedicated cache fleets and co-located caches, the
end-to-end request flow, the failure modes the distribution introduces, and a
short operational-hygiene checklist.

## Key patterns & decisions

- **Horizontal cache scaling**: partition cached data across nodes so capacity
  and throughput grow by adding machines rather than by buying a bigger one;
  a node loss removes only its shard of the cache, not the whole thing.
- **Consistent hashing for placement**: the client library hashes each key to
  choose its owning node, and the consistent variant keeps node
  additions/removals from reshuffling most of the keyspace.
- **Sharding plus replication as complementary axes**: sharding spreads
  distinct keys across nodes for capacity; replication copies a shard to
  additional nodes so a node failure does not lose that data's cached copy.
- **Client-library mediation**: applications talk to a smart client that
  encapsulates node discovery, key routing, and retrieval — the app never
  hardcodes which node holds what.
- **Dedicated vs co-located cache placement**: a dedicated cache fleet scales
  independently and isolates resources but costs more and adds a network hop;
  co-locating cache with the app gives the lowest possible latency and lower
  cost, but contends for host resources, scales only with the app tier, and
  complicates invalidation. Choose dedicated for large multi-service scale,
  co-located for small/latency-critical/budget-bound systems.
- **Invalidation as a first-class design problem**: cached copies drift from
  the source of truth, so plan time-based expiry or event-driven invalidation
  up front; the difficulty multiplies with node count and under network
  partitions, where nodes cannot even agree with each other.
- **Operational hygiene checklist**: cache only hot, relatively static data;
  set TTLs to bound staleness; load lazily (cache-aside) rather than caching
  everything; monitor hit rate, memory, and network; design for graceful node
  failure; pre-warm critical keys to avoid cold-start stampedes.
- **Engine selection**: Redis when you want rich data structures, replication,
  and persistence; Memcached when you want a minimal, pure in-memory
  key-value cache; a managed offering (e.g. ElastiCache) when you want
  multi-AZ failover and demand-based node scaling handled for you.

## When to apply / trade-offs

Introduce a distributed cache when a single-node cache saturates on memory or
becomes the availability bottleneck — typically at the many-users/large-dataset
stage. The price of distribution is a new set of correctness problems that a
single node never had: cross-node consistency, invalidation fan-out, partition
behavior, and rebalancing. The placement decision is a genuine trade rather
than a default: latency-obsessed and small systems can legitimately co-locate,
while anything that needs independent scaling of cache capacity should run a
dedicated tier. Most of the best practices reduce to one discipline — treat
the cache as an optimization with bounded staleness, never as the system of
record.

## Fidelity check

1. *Claim*: consistent hashing is used so cluster membership changes disturb
   little of the keyspace. The capture lists consistent hashing as a core
   component and says its purpose is spreading data evenly while keeping the
   impact of adding or removing nodes minimal.
2. *Claim*: co-location trades scalability and isolation for latency and
   cost. The capture lists low latency (real-time gaming, high-frequency
   trading examples) and cost efficiency as co-location advantages, against
   resource contention, whole-server upgrades to scale, and trickier
   invalidation as disadvantages.
3. *Claim*: cache warming is a recommended practice. The capture's best
   practices explicitly include pre-populating critical data into the cache to
   avoid cold starts, alongside TTLs, judicious caching, monitoring, and
   failure planning.
