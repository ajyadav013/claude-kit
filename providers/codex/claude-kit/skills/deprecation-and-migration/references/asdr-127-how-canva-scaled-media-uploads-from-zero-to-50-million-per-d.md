---
source: https://www.canva.dev/blog/engineering/from-zero-to-50-million-uploads-per-day-scaling-media-at-canva/
author: Canva Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Canva's media service: stretching MySQL, then a queue-driven live migration to DynamoDB

## What it teaches

Canva's media microservice (metadata for user uploads and the stock library:
ownership, status lifecycle, content metadata, file references) rode a
thin-service-over-RDS-MySQL design through years of hypergrowth until the
cracks became structural: multi-day then six-week schema migrations even with
an online-DDL tool, replication-rate ceilings on read replicas, EBS volume
size limits with I/O latency creeping up at each expansion, restarts
impossible without downtime because traffic needed a warm buffer pool, and a
2TB per-table filesystem cap inherited from old snapshots. The article's core
value is the migration discipline: they bought time with schema surgery and
pragmatic sharding, chose DynamoDB after prototyping (weighing a short
runway and preference for managed services), and executed a zero-downtime
live migration built on an intentionally unordered notification queue rather
than a binlog-ordered replication log. Post-cutover, latency improved
markedly, DynamoDB autoscaled through a further tripling of active users at
lower cost than the RDS fleet it replaced — while costing them ad-hoc SQL
(now served via CDC into the warehouse) and easy schema backfills.

## Key patterns & decisions

- **Read-mostly, recent-skewed workload recognition**: media metadata is written once and rarely modified, and reads concentrate on recently created items — this shaped every later choice (what to migrate first, which reads could be eventual).
- **Lifetime-extension before replatforming**: move churn-prone metadata into a self-managed JSON column, denormalize to cut joins and lock contention, shorten repeated values, drop foreign keys, reduce update chattiness — cheap moves that defer a risky migration.
- **Shard for the dominant query, accept scatter-gather for the rest**: their interim sharding optimized ID lookups (design loads) and tolerated inefficient fan-out for rarer listing queries.
- **Notification-queue replication instead of an ordered log**: enqueue only "media X was created/updated/read" markers with no payload; workers re-read the current row from the MySQL primary and upsert DynamoDB. Because each message triggers a fresh authoritative read, messages can be reordered, retried, paused, or throttled freely — sidestepping binlog parsing entirely.
- **Priority-tiered replication**: writes on a high-priority queue, read-triggered copies on a low-priority queue, workers draining high first — so DynamoDB converged fastest on the data users were actively touching.
- **Backpressured backfill scan**: a newest-first scan enqueued remaining media only while the low-priority queue stayed near empty, so bulk history never crowded out live changes.
- **Shadow reads before trusting the new store**: dual-read with result comparison flushed out replication bugs; then eventual reads shifted to DynamoDB with per-item fallback to MySQL for not-yet-copied rows; non-ID queries waited until the scan finished.
- **Rehearsed, reversible cutover**: the write switch used transactional/conditional writes to preserve the old contracts, integration tests run against both implementations, and a flag-based runbook — rehearsed through dev and staging — that could flip reads back to MySQL in seconds.
- **Honest retrospective**: DynamoDB was right for them (stable schema, rare new access patterns), but composite GSIs need manual attribute concatenation, backfills need parallel-scan code, and today they would seriously weigh managed NewSQL (Spanner/CockroachDB-class) instead.

## When to apply / trade-offs

- The unordered-queue-plus-authoritative-reread trick is the standout reusable pattern: it trades extra primary reads for enormous operational freedom (retry/reorder/pause) and applies to any migration where the source can serve point lookups.
- "Migrate hot data first" only works when access is recency-skewed; uniformly accessed data loses the early-load-shedding benefit.
- Choosing a key-value store froze their schema agility — reasonable because media metadata had stabilized; a domain still discovering its access patterns would suffer.
- The lessons the authors distill map to: exploit access patterns for ordering the work, migrate live to surface bugs early, and verify with production data because it is always stranger than fixtures.

## Fidelity check

1. Claim: MySQL pain was multi-dimensional, not just size. Support: the capture lists schema changes stretching to six weeks even with the online-migration tool, replica write-rate ceilings on MySQL 5.6, the 16TB EBS limit with latency rising at each volume increase, warm-buffer-pool dependence blocking restarts, and a 2TB table-file limit from ext3-based snapshots.
2. Claim: replication deliberately avoided ordering guarantees. Support: the article says they dodged building an ordered log or binlog parser by queueing content-free created/updated/read notifications to SQS, with workers reading current state from the MySQL primary so messages could be arbitrarily reordered or retried.
3. Claim: the bet aged well with acknowledged costs. Support: post-migration the user base more than tripled while DynamoDB autoscaled at lower cost than the replaced RDS clusters, but the team notes losing ad-hoc SQL (replaced by CDC to the warehouse), manual composite GSI construction, and that they would strongly consider hosted NewSQL today.
