---
source: https://algomaster.io/learn/system-design/sql-vs-nosql
author: AlgoMaster
license-note: ideas absorbed in own words; no text or code reproduced
---
# SQL vs NoSQL: a workload-shape decision, not a category war

## What it teaches
The chapter reframes "SQL vs NoSQL" from a binary brand choice into a bundle of
separate decisions: how the data is shaped, which queries dominate, how correct
each operation must be, how far it must scale, and whether the team can actually
operate the thing. "NoSQL" is an umbrella over key-value, document, wide-column,
graph, time-series, and search systems — each optimized for a different data
shape — while relational engines optimize for many different questions over the
same well-modeled data. It repeatedly punctures stale slogans: SQL databases can
scale horizontally with replicas/partitioning/distributed-SQL, several NoSQL
stores do offer transactions, "schemaless" data still has a schema (it just
lives in application code), and no database is fast in the abstract — only fast
for a specific workload.

## Key patterns & decisions
- **Decompose the choice into workload questions**: read/write shape, required
  correctness per operation, expected scale, and team operability — answer those
  before naming a product.
- **NoSQL is a family, not a database**: match the model to the shape — key-value
  for sessions/counters, document for whole objects read together, wide-column
  for high-write grouped events, graph for relationship traversal, time-series
  for telemetry, search engines for text ranking.
- **Categories blur in modern engines**: relational engines store JSON, document
  stores offer multi-document transactions, key-value stores offer conditional
  writes, and distributed SQL spreads relational data across machines — evaluate
  the specific engine, not the label.
- **Schema location, not schema absence**: relational engines enforce shape in
  the database and catch bad data early; flexible stores push shape into code,
  validation, and index definitions, trading migration ceremony for the risk of
  divergent, silently inconsistent records.
- **Normalize vs duplicate-for-reads**: normalization gives flexible joins and
  strong rules but coordination cost at scale; denormalized copies give fast
  known-pattern reads but every duplicate needs an explicit update strategy or
  it drifts stale.
- **Interrogate transaction scope, not existence**: for any store, ask how many
  records a guarantee covers, whether it crosses partitions, what concurrent
  readers can see, its latency cost, and its failover behavior.
- **Horizontal scaling is earned, not conferred**: key-partitioned stores make
  spreading data easier, but hot keys, oversized documents, unbounded
  partitions, and cross-partition queries can still collapse; relational systems
  go very far with indexes, replicas, partitioning, pooling, and caching.
- **Team familiarity is a reliability feature**: a database the team can back
  up, migrate, observe, and repair beats a theoretically superior one nobody
  understands; a database choice is also an on-call choice.
- **Polyglot by role**: use a relational store as the system of record and bolt
  on specialized stores for cache, search, analytics, and event workloads
  instead of forcing one engine to do everything.
- **Relational as the default until proven otherwise**: for new systems with
  evolving query needs and multi-record correctness (money, orders, inventory),
  start relational; migrate a workload to NoSQL only when its model directly
  matches, not because it "sounds scalable."

## When to apply / trade-offs
Use this framing at datastore-selection time and in design reviews when someone
proposes a store by brand. The chapter's mistake list doubles as a review
checklist: picking NoSQL to dodge data modeling, forcing SQL onto search/graph/
time-series shapes, assuming NoSQL lacks transactions or SQL lacks scale,
ignoring on-call familiarity, and confusing replicas with backups (replication
propagates mistakes just as fast as data). The main trade-off it keeps
foregrounding: denormalized speed always arrives with a stale-copy repair
obligation.

## Fidelity check
1. Claim: the chapter treats "NoSQL" as several distinct models with distinct
   fits. Support: the capture tabulates key-value, document, wide-column, graph,
   time-series, and search types, each paired with example workloads like
   sessions/caches, profiles/catalogs, event writes, fraud rings, telemetry,
   and text ranking.
2. Claim: it debunks the vertical-vs-horizontal scaling slogan. Support: the
   capture calls that older picture too simple, lists relational scaling tools
   (replicas, partitioning, sharding, pooling, caching, distributed SQL), and
   notes NoSQL scaling still fails under bad partition keys, hot keys, and
   many-partition queries.
3. Claim: it warns replication is not backup. Support: the capture's
   common-mistakes list includes treating replicas as backups, with the reason
   that replication copies mistakes quickly.
