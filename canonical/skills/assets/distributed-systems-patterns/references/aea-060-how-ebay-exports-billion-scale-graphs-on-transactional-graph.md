---
source: https://innovation.ebayinc.com/stories/how-we-export-billion-scale-graphs-on-transactional-graph-databases/
author: eBay Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Exporting a 15-billion-vertex graph from a transactional store without touching production traffic

## What it teaches
eBay's graph platform (NuGraph: JanusGraph on top of FoundationDB) serves
short transactional queries — the backing store caps any transaction at five
seconds, so a query can only ever touch a small subgraph. But fraud/anomaly
analytics and data-quality auditing need the *whole* graph, which for the largest
internal dataset means 15B+ vertices and 24B+ edges. The article describes an
export pipeline that full-scans the store into HDFS via Spark in about 3 hours,
and the engineering required to get there: traffic isolation, partition-boundary
correctness, supernode handling, and a series of JVM memory fixes that only
manifest at billions of elements.

The meta-lesson: OLTP and full-scan analytics must be physically separated, and
"it works at hundreds of millions" says nothing about billions — the failure modes
that appeared were all in library internals (caches, serializers, broadcast
variables), found through profilers and heap analysis, and fixed upstream.

## Key patterns & decisions
- **Scan the disaster-recovery replica, not production**: a DR cluster continuously
  syncs from the primary (observed lag under ~6 seconds) and absorbs the full-scan
  load. The earlier idea — restore from backup snapshots — was dropped because
  restoring a graph this size takes days before export can even begin.
- **Resumable iterator around a hard transaction limit**: since no FoundationDB
  transaction may exceed five seconds, the scanner catches the timeout, records the
  last key reached, and opens a fresh transaction from that checkpoint — turning a
  bounded-transaction store into an effectively unbounded scan.
- **Storage-partition-to-Spark-partition mapping with vertex-aware alignment**: the
  KV store's key ranges know nothing about graph encoding, so a vertex's properties
  and edges (stored as a contiguous key run) can straddle two ranges and appear as
  duplicated/partial vertices. Range boundaries must be snapped to vertex
  boundaries before handing ranges to executors.
- **Supernode co-location**: vertices with ~1M+ edges span many contiguous ranges;
  all of a supernode's ranges must be pinned to one Spark partition so its reader
  sees the vertex whole. Supernodes also blow up file sizes and memory if untreated.
- **Profile-then-replace cache fix**: >10% GC overhead across executors was traced
  (async profiler flame graphs + heap-dump analysis) to a Guava LRU cache — a
  16-entry schema cache hit ~3 billion times, where every read enqueues bookkeeping
  objects. Swapping in Caffeine (ring-buffer read recording) erased the GC cost,
  ~3x overall speedup; the fix was upstreamed to JanusGraph.
- **Cut a Spark shuffle stage from the export program**: the generic BSP vertex-
  program path did an unnecessary shuffle for the pure-copy export case; a targeted
  TinkerPop optimization dropped it from three stages to two (~1.4-1.5x), also
  contributed upstream.
- **Debug-string OOM**: a broadcast-variable wrapper's string rendering could
  materialize enormous collections purely for UI display, causing out-of-memory on
  big graphs; truncating that rendering fixed it (again upstreamed).
- **Post-export graph QA**: with the graph in HDFS, run structural audits — ghost
  vertices (degree zero), degree-threshold violations flagging load bugs, and a
  power-law degree-distribution check as a sanity signature of a healthy
  real-world relationship graph. Excessive-degree vertices feed an edge-pruning
  loader to keep transactional latency bounded.

## When to apply / trade-offs
- Any system with a transactional store plus periodic bulk-analytics needs this
  separation; a continuously-synced replica beats snapshot-restore whenever data is
  large relative to restore throughput.
- The vertex-alignment problem generalizes: whenever a logical record is encoded as
  multiple contiguous KV pairs, naive range-partitioned parallel scans corrupt
  records at boundaries — align splits to logical record boundaries.
- Checkpoint-resume iterators apply to any backend with hard per-transaction time
  or size limits.
- Costs: a dedicated DR cluster (one datacenter vs the primary's three), a 380-core
  / 3.7 TB Spark footprint, and export freshness bounded by run cadence (hours).

## Fidelity check
1. Claim: the five-second transaction ceiling forced a checkpoint-resume scanner.
   Capture support: the article states FoundationDB queries cannot run longer than
   five seconds and describes a resumable iterator that catches the timeout and
   restarts a new transaction from the last scanned key.
2. Claim: a tiny schema cache accessed billions of times triggered the Guava GC
   pathology. Capture support: the text reports a VertexCache of only 16 schema
   entries whose read path was invoked roughly 3.02 billion times during a
   160M-vertex export, and that LRU read-side bookkeeping caused the object churn
   that Caffeine's design avoids.
3. Claim: snapshot restore was rejected because it takes days at this scale.
   Capture support: the solution section says the initial backup/restore-based
   approach could take days to restore a billions-scale graph before export could
   start, which motivated the DR-cluster approach with only seconds of sync lag.
