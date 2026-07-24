---
source: https://algomaster.io/learn/system-design/change-data-capture-cdc
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Change Data Capture: streaming committed row changes instead of polling for them

## What it teaches

When a production database is the source of truth but its data must also appear in a search
index, cache, warehouse, fraud system, or sibling service, the naive answer is periodic batch
copy jobs — which deliver stale data, repeatedly scan the source, and fail messily mid-run.
CDC replaces polling with a stream: committed inserts, updates, and deletes are captured at the
database and forwarded as change events. The pipeline is capture → normalize into a change-event
shape (operation, table, primary key, before/after images, commit position, commit timestamp,
transaction context) → publish to a stream/topic → consume downstream. A hard invariant: only
*committed* changes may ever be published; rolled-back writes must remain invisible.

## Key patterns & decisions

- **Three capture strategies with an explicit ranking**: timestamp-column polling (simple,
  portable, but misses hard deletes, skips intermediate versions between polls, and depends
  on updated_at discipline and indexing); trigger-based (captures deletes and before/after
  values, powers audit tables and outboxes, but adds latency to every write and the trigger
  itself becomes production code that can break writes); log-based (tail the WAL/binlog/oplog
  the database already writes — commit-ordered, low write-path impact, resumable from a saved
  log position — the recommended production default, at the cost of database-specific setup
  and ongoing care).
- **CDC ≠ domain events ≠ event sourcing**: CDC says "this row changed"; a domain event says
  "this business fact happened"; event sourcing makes the append-only event log the primary
  record. One checkout may touch four tables — consumers usually want one OrderPlaced fact,
  not four row diffs.
- **Transactional outbox via CDC**: write the business rows and an outbox event row in one
  transaction, then let CDC stream the outbox table — eliminating the dual-write hazard where
  the DB commit succeeds but the broker publish fails (or vice versa).
- **Canonical use cases**: search-index sync, warehouse/lakehouse feeds faster than nightly
  batch, cache invalidation (delete-and-rebuild is safer than in-place cache updates), read
  models across services (with a warning that raw table replication creates hidden coupling),
  and audit/compliance trails with predefined retention and access rules.
- **Snapshot-then-stream lifecycle**: most connectors need an initial full-table snapshot
  before streaming; plan for its duration, source load, and the consumer-side flood of
  historical rows.
- **Log-retention as a recovery precondition**: if the connector is down longer than the
  database retains its log, resumption fails and a fresh snapshot is needed; PostgreSQL
  replication slots can silently pin WAL and fill disks.
- **Late-event defense**: source commit order can be scrambled by partitioning and parallel
  consumers, so consumers dedupe/order by primary key + version/commit position/timestamp.
- **Deliberate delete semantics**: decide up front whether downstream systems hard-delete,
  soft-delete, tombstone, or retain for compliance.
- **Least-privilege, column-filtered streams**: capture only needed tables/columns, mask
  sensitive fields, encrypt, restrict topic readership, and apply personal-data retention —
  CDC otherwise exfiltrates entire tables by default.
- **Schema evolution discipline**: additive changes, versioned event formats, and testing
  migrations against CDC consumers before release; the stream is a contract.

## When to apply / trade-offs

Reach for CDC when the database is authoritative and multiple systems need a near-real-time
copy without burdening the request path with dual writes. Prefer log-based capture for
high-volume systems; accept timestamp polling only for small, low-stakes syncs tolerant of
missed intermediate states. Route *business* meaning through outbox/domain events rather than
letting consumers reverse-engineer intent from raw row diffs — casual CDC leaks schema details
across service boundaries and spreads sensitive columns. Operationally, treat the pipeline as
a production system: monitor connector lag, oldest unprocessed event age, destination write
failures, DLQ volume, and rehearse snapshot/restart/replay before an incident forces it.

## Fidelity check

1. Claim: log-based CDC is the preferred production approach because it reuses the recovery/
   replication log. Support: the capture explains the database already writes WAL/binlog/oplog
   during normal operation, giving commit-order fidelity, low application-write impact, and
   resume-from-offset after outages, while naming it the best (but not set-and-forget) default.
2. Claim: the outbox pattern fixes the dual-write problem by making event emission transactional.
   Support: the capture describes writing the business data and an outbox row in the same
   transaction so CDC publishes the event only if the transaction commits, and nothing is
   published on rollback.
3. Claim: timestamp-based polling silently loses hard deletes and intermediate versions.
   Support: the capture's downside list for timestamp CDC includes deleted rows vanishing
   without soft deletes and a row changed three times between polls surfacing only its final
   state, plus clock-precision and missing-index pitfalls.
