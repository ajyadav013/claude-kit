---
source: https://www.amazon.science/blog/lessons-learned-from-10-years-of-dynamodb
author: Amazon Science
license-note: ideas absorbed in own words; no text or code reproduced
---

# A decade of running DynamoDB: predictability, adaptive partitioning, and continuous verification

## What it teaches

A retrospective by two DynamoDB principal engineers (companion to their USENIX ATC 2022 paper)
on what it took to keep a managed NoSQL service stable, durable, and highly available for ten
years. The core message: at large scale, a system that behaves the same way under every condition
beats a system that is faster on the happy path but degrades differently on the unhappy one.
Three replicated copies per partition across availability zones, a leader per replication group,
and a request-router front end form the substrate; the lessons are about how that substrate is
kept honest over time.

## Key patterns & decisions

- **Predictability over absolute efficiency.** A cache with a ~99.75% hit rate looked like a win,
  but a cache failure meant the backing metadata store had to absorb a 400x request jump
  instantly — a bimodal system where hit and miss paths behave radically differently is a
  cascading-failure factory.
- **Constant-work design.** After introducing MemDS (a horizontally scaled, compressed in-memory
  replica of all routing metadata), every request is forwarded to MemDS asynchronously even when
  the local cache answers it. The fallback path is exercised on every request, so backing traffic
  is proportional to customer traffic and a cache outage changes nothing downstream.
- **Reshape partitions around observed traffic, not just size.** Allocating capacity evenly by
  partition size produced hot partitions (skewed key access) and throughput dilution (splits that
  left each child too little capacity). The fixes evolved from bursting (borrow unused node-level
  headroom for short spikes) to adaptive capacity (reactive repartitioning of hot items) to
  global admission control — token buckets replenished centrally, held locally at each request
  router, plus a second bucket layer at the partition level.
- **Continuous verification of data at rest.** A scrub process constantly checksums all three
  live replicas against each other and against a reference replica rebuilt offline from archived
  write-ahead logs. The authors call this the single most reliable defense against silent
  corruption, hardware decay, and even their own software bugs.
- **Log replicas for fast quorum healing.** Rebuilding a full storage replica (B-tree plus logs)
  takes minutes; attaching a log-only replica takes seconds because only recent write-ahead log
  entries are copied. The quorum is restored almost immediately and durability of fresh writes is
  never in a two-copy window for long.
- **Formal methods buy the freedom to change.** Because the replication protocol is Paxos with
  provable properties, the team could introduce structural changes like log replicas without
  fearing correctness regressions — proofs, game days, upgrade/downgrade tests, and deployment
  safety tooling are framed as enablers of evolution, not bureaucracy.
- **Measure availability where the customer stands.** Beyond server-side metrics, availability is
  tracked via internal AWS services reporting their observed DynamoDB error rates and via canary
  applications running in every AZ against every public endpoint; customer-facing alarms fire on
  client-perceived error thresholds.
- **Treat read and write availability separately.** Write availability needs a healthy leader and
  a two-of-three quorum; consistent-read availability needs a leader; eventual reads need any
  replica. Different failure responses apply to each.
- **Chaos testing with verification.** Regular power-off tests kill random nodes under realistic
  simulated traffic, then tooling validates the surviving data is logically intact.

## When to apply / trade-offs

- Constant-work/anti-bimodality applies to any cache or fallback layer in front of a scarce
  backend: pay a steady tax (always touch the backend) to eliminate the failure cliff. The cost
  is deliberate inefficiency — you provision the backend for 100% of traffic even at high hit
  rates.
- Traffic-adaptive partitioning matters when workloads are skewed and shift over time; static
  even splits are simpler but guarantee hot spots eventually.
- Continuous scrubbing costs constant background I/O and an offline rebuild pipeline; justified
  when durability targets are extreme and silent corruption is unacceptable.
- Log-replica-style "cheap partial member" healing is worth copying in any quorum system where
  full state transfer is slow.
- Client-side canaries add fleet cost but catch what server metrics structurally cannot (network
  path, endpoint, DNS issues).

## Fidelity check

1. Claim: the original router cache was near-perfect yet dangerous. Support: the capture states
   the local routing-metadata cache hit about 99.75%, but a miss storm would force the metadata
   table to go from serving 0.25% of requests to 100% at once, risking cascading failure.
2. Claim: log replicas restore quorum in seconds versus minutes. Support: the capture explains
   healing a full storage replica takes minutes because the B-tree must be copied, while adding a
   log replica takes seconds since only recent unarchived write-ahead logs (typically a few
   hundred MB) are transferred.
3. Claim: verification compares live data against an independently reconstructed copy. Support:
   the capture describes the scrub process checking that all three replicas agree and that live
   replicas match a reference replica built offline from archived write-ahead-log entries, via
   checksums.
