---
source: https://blog.zomato.com/building-a-cost-effective-logging-platform-using-clickhouse-for-petabyte-scale
author: Zomato Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Replacing Elasticsearch with ClickHouse for petabyte-scale log search

## What it teaches
Zomato's services emit up to 150 million log lines per minute — over 50 TB
uncompressed per day. Self-hosted Elasticsearch buckled operationally and
financially: clusters had to be over-provisioned for bursty traffic and still
degraded. An intermediate attempt (ORC files on S3 queried through Trino) slashed
cost but missed the latency targets — sub-second queries and under-a-minute
ingestion lag were non-negotiable. ClickHouse's shared-nothing columnar design hit
both goals, and the article catalogs the design decisions that made a ~10-node
ARM cluster carry the whole load.

The transferable insight is that a log platform is a systems-design exercise across
the whole path — ingestion batching, schema shape, index choice, lifecycle tiering,
query admission control — not just a storage-engine swap.

## Key patterns & decisions
- **Custom ingestion workers over built-in connectors**: instead of ClickHouse's
  Kafka plugin, lightweight Golang workers batch messages (up to ~20k rows per
  table, flushing within ~5s) and insert using ClickHouse's native wire format,
  which they measured ~1.8x faster and less I/O-heavy than HTTP inserts. Workers
  run on spot instances and round-robin across nodes, skipping unhealthy ones.
- **Semi-structured schema with a catch-all map**: frequently-queried fields are
  first-class columns (with per-column codecs and low-cardinality string encoding
  for compression); everything unrecognized lands in a string-to-string map column
  that the query API flattens back out for clients.
- **Fix the schema at the source with a logging SDK**: an in-house structured-logging
  SDK standardizes top-level fields (caller, timestamp, stream) so developers emit
  key-value fields instead of grepping a free-text message column.
- **Bloom-filter token index for substring search**: a token-based bloom filter
  secondary index lets LIKE-style searches skip non-matching data parts; they sized
  the filter from the standard false-positive/size formulas (~235 KiB per 8k-row
  block at p=0.1 with 3 hash functions). ClickHouse's experimental inverted index
  was tried and rejected for memory instability.
- **No replication, by design**: they dropped replicas (and thus ZooKeeper) because
  data already persists to S3 and EBS volumes are backed up; recovery is
  re-attaching the volume to a fresh node. Simpler operations traded against
  availability during node loss.
- **Hot/cold tiering with TTL**: data moves to a cold tier after 24 hours and is
  deleted at 3 months; ARM (Graviton) instances with multiple gp3 volumes serve the
  CPU- and IO-bound workload.
- **Query admission control as resilience**: per-user and system-level throttling,
  selective killing of resource-hogging queries, and lowering read priority so
  writes win under pressure.
- **Table-level p95 query-time monitoring**: watching per-table latency percentiles
  drives decisions like adding indexes or changing sort keys.
- **DOM virtualization in the log viewer**: the custom dashboard renders only
  viewport-visible rows because result sets are huge (~3k records per MB).

## When to apply / trade-offs
- Fits when log volume makes per-GB indexing engines (ELK) cost-prohibitive but you
  still need interactive search; a data-lake + query-engine approach is cheaper
  still but sacrifices latency and freshness.
- Skipping replication is only sane with an object-store + volume-backup safety
  net and tolerance for brief per-node unavailability.
- The catch-all map column trades some query ergonomics/performance on rare fields
  for schema flexibility; the SDK push is the long-term fix.
- Claimed results: ingestion lag under 5 seconds, p99 query time around 10 seconds
  (7-day scans on the largest table under 20s), and potential savings above a
  million dollars a year versus the prior stack.

## Fidelity check
1. Claim: the S3/ORC/Trino detour was rejected on latency, not cost. Capture
   support: the article says that approach cut cost substantially but could not
   keep queries under ~10s and had 5-10 minutes of ingestion lag from writing
   large files, against targets of ~1s queries and <1 minute lag.
2. Claim: native-format batch inserts via custom Go workers were the ingestion
   path. Capture support: the text describes Golang workers on spot instances
   batching up to 20,000 messages per table with max 5s lag and a ~1.8x speedup
   from the native format versus HTTP.
3. Claim: they deliberately run without replication or ZooKeeper. Capture support:
   the replication section states they opted out of both to simplify operations,
   relying on S3 persistence and EBS backups, with a replacement node re-attaching
   the volume after failure.
