---
source: https://algomaster.io/learn/system-design/vertical-vs-horizontal-scaling
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Choosing between scaling up and scaling out, layer by layer

## What it teaches

That scaling is not a binary religion but a per-component decision that starts
with identifying the actual bottleneck. Scaling up (bigger machine) and
scaling out (more machines) each match different workload shapes, and mature
systems deliberately mix both — a fat database primary under a fleet of thin
stateless app servers is the canonical hybrid. The chapter ends with an
ordered decision procedure rather than a slogan.

## Key patterns & decisions

- **Bottleneck-first scaling**: measure CPU, memory, disk I/O, network, GPU
  memory, tail latencies (p95/p99), queue depth, DB waits, and cost-per-request
  before touching capacity; scaling before measuring hides the real problem.
- **Scale up for stateful, scale out for stateless**: components that own data
  (databases, caches, search nodes) benefit from bigger boxes first because
  splitting state buys routing, replication, rebalancing, and recovery
  complexity; stateless HTTP tiers and queue workers scale out cleanly when
  session/file state lives externally.
- **Vertical's failure modes**: a hard instance-size ceiling, sharply
  super-linear pricing at the top end, restart/failover pain on resize, and
  concentrated blast radius — one huge node dying takes everything with it.
- **Horizontal's hidden costs**: partial failures, retry/timeout logic,
  coordinated deploys, consistency edge cases from replication and sharding,
  slowest-of-N fan-out latency, and non-instant node warm-up (cache fill,
  model load, cluster join).
- **Shared-dependency ceiling**: adding app servers cannot raise the write
  limit of the database behind them — it only reaches that limit faster. Fleet
  growth must be paired with protecting the shared tier.
- **Layer-specific scaling rules**: read replicas help read traffic but writes
  need partitioning/sharding; caches shard but a single hot key still pins one
  node; search/vector shards add capacity while making rebalancing, ranking,
  and scatter-gather queries harder; inference replicates model copies but
  large models may instead need bigger GPUs, batching, or model splitting.
- **Queue depth as the autoscaling signal for workers**: a persistently
  growing backlog is the cleanest indicator that the worker pool is
  undersized; workers must also be retry-safe since failed jobs re-run.
- **Remove waste before adding capacity**: slow queries, missing indexes,
  runaway retries, and oversized payloads are cheaper to fix than any scaling
  move and often eliminate the "need" to scale at all.
- **Backpressure protects the hybrid**: connection limits, rate limits,
  queues, and load shedding let the system slow, buffer, or reject excess work
  before an overloaded shared dependency cascades.
- **Bottleneck migration**: after any meaningful capacity change the
  constraint moves somewhere else, so re-test under realistic load each
  iteration rather than declaring victory.

## When to apply / trade-offs

- A bigger box is the fastest safe move when one machine is clearly saturated,
  when hot data almost fits in RAM, or when the code (legacy monolith, tight
  coupling) can't be distributed yet — buying time is a legitimate strategy.
- Scale out when the service must survive machine loss, traffic is bursty,
  work items are independent (requests, jobs, tenants, embeddings), the next
  bigger instance doesn't exist or costs too much, or users/data-residency
  rules demand regional placement.
- The chapter explicitly rehabilitates vertical scaling: running years on one
  large database can be more reliable than premature distribution.
- "Just scale horizontally" is called out as incomplete advice because the web
  tier scaling easily says nothing about the database, embedding pipeline, or
  GPU tier that then becomes the limit.
- Autoscaling (both directions) doesn't replace design — it still depends on
  good metrics, startup time, shared-dependency headroom, and safe deploys.

## Fidelity check

1. *Claim: adding web servers cannot exceed the database's write ceiling.* The
   capture gives a concrete figure: if the primary handles 20k writes/sec,
   adding 50 more web servers doesn't raise that number — it may just make the
   database fail sooner.
2. *Claim: the chapter prescribes an ordered decision procedure.* The capture
   lists a six-step framework: find the bottleneck with metrics/traces, remove
   obvious waste, scale vertically for simple headroom, scale horizontally for
   failure-survival/bursts/capacity, protect shared dependencies with
   backpressure mechanisms, then re-test because the bottleneck moves.
3. *Claim: hot keys defeat cache sharding.* In the layer-by-layer section the
   capture notes that replicating or splitting cache data helps, but one very
   popular key can still overload the single node that owns it.
