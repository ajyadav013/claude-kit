---
source: https://www.uber.com/en-IN/blog/mysql-at-uber/
author: Uber
license-note: ideas absorbed in own words; no text or code reproduced
---

# Uber's MySQL control plane: goal-state convergence for 2,300+ clusters

## What it teaches

Uber runs its core services on a fleet of more than 2,300 independent MySQL
clusters and set out to lift fleet availability from three nines to four
nines. The article (first of a series) describes the re-architected control
plane that made that possible. The central idea is a declarative,
state-based platform: a "technology manager" publishes each cluster's
desired state (node counts, roles, resource profiles, server settings,
sidecars) to Odin, Uber's technology-agnostic stateful-platform manager,
and the system continuously converges reality toward that goal state. All
mutations flow through durable, fault-tolerant workflows (built on
Cadence), and a separate observer component (the "controller") watches
health signals and triggers corrective workflows — most importantly
automated primary failover.

The re-architecture was motivated by two concrete failures of the old
design: the MySQL control logic was tightly coupled to generic
infrastructure placement processes (so database failures blocked
infrastructure operations and vice versa, degrading 60+ operational
workflows), and cluster state lived in a Git-backed config store that was
never designed to be a runtime state database. The redesign decoupled the
layers and moved topology into a strongly consistent etcd store whose
watch events drive proxy reconfiguration.

## Key patterns & decisions

- Goal-state/desired-state convergence as the control-plane contract: the
  manager declares the target; a per-node worker sidecar and the placement
  engine converge the actual state to it.
- Durable workflow engine (Cadence) for every long-running infrastructure
  operation — failover, node add/replace/delete, variable changes,
  replication rewiring — giving fault tolerance and resumability.
- Observer/actor separation: a controller with a rule evaluator consumes
  health signals and initiates mitigation workflows (e.g., auto primary
  failover) rather than embedding reactions inside the data path.
- Two-tier failover taxonomy: graceful (old primary alive — fence it
  read-only, drain traffic, elect the most binlog-advanced replica
  preferring the same data center, wait for catch-up, then enable writes)
  versus emergency (old primary unreachable — same flow minus any reliance
  on the dying primary).
- Node replacement decomposed into node-add + node-delete with explicit
  invariants: identical hardware profile, equivalent fault-domain
  placement so latencies stay constant, rewiring of replication children,
  and a graceful primary promotion first if the victim is the primary.
- Schema-change automation with strategy selection: instant ALTER for
  cheap/safe changes, an online non-blocking tool (Percona's
  pt-online-schema-change) for heavier ones — chosen automatically by
  change type and data size; plus a dry-run on an isolated replica and
  schema-as-code integrated into CI/CD so merged schema files trigger the
  change workflow.
- Sidecar-decomposed data-plane node: the MySQL process runs alongside
  separate containers for goal-state convergence, metrics polling, health
  probing, and an ephemeral backup job — each with one job.
- Discovery via a static VIP + reverse proxy: a pooling service rewrites
  proxy config from etcd watch events, routing writes to the primary and
  load-balancing reads across replicas with same-region preference;
  per-node traffic disabling supports safe debugging and drains.
- Standard supporting planes: binlog-based CDC (Storagetapper → Kafka →
  Hive), automated backup/restore (XtraBackup) with a 4-hour RPO, and
  prober-driven synthetic-traffic observability with alerting on write
  unavailability, replication lag, and connection anomalies.

## When to apply / trade-offs

- The decoupling lesson is the transferable core: when a
  technology-specific control plane shares a fate with generic
  infrastructure tooling, failures cross-contaminate; a clean interface
  (here, goal-state publication) isolates them.
- Git as a runtime state store is called out as a mismatch — version
  control is for change review, not for high-churn topology state that
  needs strong consistency and watches; etcd-style stores fit better.
- The graceful/emergency failover split encodes a real trade-off: the
  graceful path preserves all data by waiting for replication catch-up,
  while the emergency path accepts that the old primary cannot be
  consulted — worth modeling explicitly rather than having one path.
- Dry-run-on-replica for schema changes buys backward-compatibility
  confidence cheaply and pairs naturally with schema files reviewed in the
  normal code-review pipeline.

## Fidelity check

1. Claim: the fleet exceeds 2,300 clusters and the effort raised
   availability from 99.9% to 99.99%. Support: the capture opens by
   stating Uber operates over 2,300 independent MySQL clusters and spent
   recent years improving fleet availability from 99.9% to 99.99% via
   optimizations and a control-plane re-architecture.
2. Claim: graceful failover fences the old primary read-only, drains
   traffic, elects the most binlog-advanced same-DC replica, waits for
   transaction catch-up, then enables writes. Support: the capture lists
   exactly these steps for the graceful promotion workflow, including the
   same-data-center default and precedence for the most advanced binlog
   position.
3. Claim: schema changes pick between instant ALTER and
   pt-online-schema-change automatically and support replica dry-runs plus
   CI/CD triggering. Support: the capture describes the workflow selecting
   instant-alter for quick column additions versus ptosc for datatype
   changes, a dry-run capability on an isolated replica, and CI detecting
   merged schema files to trigger the change workflow.
