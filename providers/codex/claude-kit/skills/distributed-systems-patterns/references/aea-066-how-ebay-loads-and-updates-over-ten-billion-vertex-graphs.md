---
source: https://innovation.ebayinc.com/stories/graphload-a-framework-to-load-and-update-over-ten-billion-vertex-graphs-with-performance-and-consistency/
author: eBay
license-note: ideas absorbed in own words; no text or code reproduced
---

# Exactly-once bulk loading of a 15-billion-vertex graph via idempotent transactional upserts

## What it teaches
How eBay's GraphLoad utility feeds its NuGraph platform (JanusGraph on a FoundationDB
backend) with both streaming and batch data at massive scale — north of 15B vertices and
20B edges in production since 2020 — while the graph is simultaneously serving live
queries. The core insight: you do not need distributed exactly-once delivery machinery if
every write is an idempotent upsert executed inside an ACID transaction. At-least-once
replay (Kafka committed offsets for streams, a file-assignment manager for batches) plus
idempotent writes composes into an exactly-once outcome. A second theme is a fully
model-driven ETL pipeline: data layouts, vertex/edge schemas, field mappings, and
per-property update policies are all configuration, so one generic loader serves every
application domain.

## Key patterns & decisions
- **Idempotent check-then-create upserts inside one transaction**: each traversal looks a
  vertex up by its unique composite-indexed key, creates it only if absent, then applies
  property updates — so replaying the same input never duplicates graph elements.
- **Exactly-once = at-least-once replay + idempotent writes**: crashed loaders simply
  re-run from a file checkpoint or the Kafka committed offset; correctness comes from the
  write pattern, not from delivery guarantees.
- **Batch many upserts per ACID transaction for throughput**: a whole subgraph (average
  ~15 vertices plus edges/properties in production) commits atomically; batch size is
  tuned down when the backend's five-second transaction ceiling is hit.
- **Central work manager for batch files, broker offsets for streams**: a Loader Manager
  with its own state DB assigns files to ~200 parallel loader instances and reassigns
  incomplete ones; for streaming, Kafka's own consumer-offset commit plays that role.
- **Failure-specific retry taxonomy**: transaction conflicts from concurrent loaders get
  exponential-backoff retry; unknown-commit-result errors are safe to retry because the
  writes are idempotent; transaction-too-old errors trigger batch-size reduction.
- **Model-driven ETL configuration**: input layout files (delimited/CSV/JSON/Avro/hybrid)
  turn lines into key-value pairs; XML schema + mapping files turn those into vertices and
  edges, with per-property update policies (always / never / add-if-missing / min / max).
- **Asymmetric three-datacenter topology**: two DCs hold full data replicas and serve
  traffic, a third holds only transaction logs for availability; the service tier is
  deliberately not deployed in the log-only DC to avoid guaranteed cross-DC read latency.
- **Read-back validation with optional sampling**: after loading, the pipeline re-extracts
  key-values from source lines, fetches the corresponding subgraph, and compares —
  exhaustively for absolute assurance or on a sampled subset to trade certainty for time.

## When to apply / trade-offs
- Reach for the idempotent-upsert pattern whenever parallel writers plus retries threaten
  duplication and the store gives you multi-item transactions; it is far simpler than
  two-phase dedup ledgers. It fails without a unique-key index maintained in the same
  transaction as the write.
- The article explicitly explains why naive "insert and let the unique index throw"
  breaks under batching: one pre-existing item aborts the whole batch forever, so retries
  can never make progress. Upsert-per-element inside the batch is what makes retry safe.
- Big batches amortize transaction overhead but collide with backend transaction time
  limits; make batch size a tunable and back off dynamically.
- Config-driven schema mapping pays off when many teams share one loader; the cost is an
  XML/DSL surface that must be documented and validated.
- Full read-back validation is expensive at tens of billions of elements; sampling gives
  statistical confidence instead of proof — an explicit, acceptable trade.

## Fidelity check
1. Claim: replay plus idempotent traversals yields exactly-once loading. Support: the
   capture states loaders can crash and re-process the same file or stream data repeatedly
   without creating redundant graph elements because queries are built as
   add-if-not-exists, resuming from Load Manager checkpoints or Kafka committed state.
2. Claim: the backend imposes a five-second transaction ceiling that bounds batch size.
   Support: the capture describes a transaction-too-old failure mode from FoundationDB's
   five-second limit and says the loader responds by shrinking the number of vertices and
   edges per batch.
3. Claim: the third datacenter stores only transaction logs, not data copies. Support:
   the capture's deployment section says DC 2 serves as the transaction-log store for high
   availability while DC 1 and DC 3 each host three data copies, and that no service tier
   runs in DC 2 because its reads would always cross datacenters.
