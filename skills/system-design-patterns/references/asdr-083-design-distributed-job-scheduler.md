---
source: https://blog.algomaster.io/p/design-a-distributed-job-scheduler
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Architecture of a fault-tolerant distributed job scheduler

## What it teaches

How to build a service that accepts millions of one-time and recurring jobs,
fires them at the right moment, runs them on a fleet of workers, and survives
the death of any single machine. The walkthrough follows a classic interview
structure: requirements, component decomposition, API surface, then deep dives
into the parts that actually break at scale (the scheduler poll loop, worker
crashes, and the coordinator itself).

## Key patterns & decisions

- **Five-component decomposition**: a submission API layer, a persistent job
  store, a scheduling service that finds due work, a distributed queue as the
  buffer, and an execution service (coordinator + worker pool). Each layer can
  scale and fail independently.
- **Separate tables for identity, attempts, timing, and fleet state**: one
  table for job metadata, one appending a row per execution attempt (so retries
  leave an audit trail), one holding the next fire time per job, and one
  tracking worker health/capacity. Recurring jobs simply get their next fire
  time rewritten after every run.
- **Poll-by-due-minute scheduling**: the scheduler wakes on a fixed cadence and
  selects every schedule row whose next fire time equals the current tick, then
  enqueues those jobs and flips their status. Partitioning that table on the
  fire-time column keeps the per-tick query cheap.
- **Segment-sharded scan to parallelize the scheduler**: when one poller can't
  drain a hot minute (e.g., tens of thousands of jobs due at once), an extra
  segment column logically shards schedule rows; each scheduler worker scans
  only its assigned segments, so no two workers ever pick up the same job. A
  coordinator reassigns segments on membership changes or load spikes.
- **Queue as the decoupling seam**: a broker (Kafka/RabbitMQ-class) sits
  between "job is due" and "job is running", absorbing bursts and letting the
  worker fleet pull at its own pace.
- **Bounded retries with exponential backoff**: failed jobs increment a retry
  counter and re-run only below a max-attempts cap; retries are delayed on an
  increasing schedule rather than fired immediately, so transient faults don't
  cause hot retry loops.
- **Two-track worker-failure recovery**: heartbeats plus deeper health probes
  detect a dead worker; its not-yet-started jobs are simply re-queued, while
  in-flight jobs either restart from a persisted checkpoint or are marked
  failed and re-queued whole.
- **Leader election to de-SPOF the coordinator**: multiple coordinator
  replicas with consensus-based election (Raft/Paxos via zookeeper/etcd-style
  tooling), all reading shared state from a distributed store so a newly
  elected leader resumes with current data.
- **Three-tier rate limiting**: caps at submission (per-client quota), at
  queue ingress (throttled enqueue rate), and at workers (max concurrent jobs
  per node) so no single layer can be flooded into collapse.
- **NoSQL for the job store**: with a fixed schema, balanced read/write
  volume, millions of rows per day, and no need for joins or multi-row
  transactions, a wide-column/KV store is picked over a relational database
  for write throughput.

## When to apply / trade-offs

- The segment-column trick is a lightweight alternative to a full work-stealing
  or lease-based scheduler; it costs a coordinator and rebalancing logic but
  guarantees non-overlapping scans without distributed locks.
- Minute-granularity polling is simple and horizontally scalable but bounds
  scheduling precision; sub-second SLAs need a different trigger mechanism.
- Checkpointing long jobs adds write overhead per checkpoint interval; for
  short idempotent jobs, plain re-run-from-scratch is cheaper.
- The design consciously punts on priorities and inter-job dependencies —
  adding those later touches the queue choice and the scheduler query.
- Exactly-once is softened to effectively-once: the requirement is phrased as
  minimizing duplicate execution, not eliminating it, which is the honest
  distributed-systems position.

## Fidelity check

1. *Claim: scheduler scale-out uses a segment column so workers scan disjoint
   subsets.* The capture describes adding a segment column to the schedules
   table, workers querying by fire time AND their assigned segment list, and a
   coordinator rebalancing segment assignments on failure or traffic spikes.
2. *Claim: retries are capped and exponentially backed off.* The capture says
   the retry counter is compared against a max-retries threshold, after which
   the job is permanently failed, and that re-attempts should be delayed with
   exponentially growing waits (illustrated as roughly 1, then 5, then 10
   minutes) rather than run immediately after a transient failure.
3. *Claim: coordinator SPOF is addressed with leader election over shared
   state.* The capture recommends running several coordinator nodes with one
   elected leader via a consensus algorithm (Raft/Paxos, using tools like
   ZooKeeper or etcd), with standbys taking over on failure and all replicas
   reading the same job/worker state from a distributed database.
