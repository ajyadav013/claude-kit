---
source: https://www.uber.com/en-IN/blog/how-ledgerstore-supports-trillions-of-indexes/
author: Uber Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Indexing an immutable financial ledger at trillion scale: three index classes, three consistency budgets

## What it teaches

LedgerStore is Uber's append-only source of truth for money movement. Because
ledgers are immutable and read through many different access patterns, the
system needs on the order of trillions of index entries over hundreds of
billions of records. The article's core lesson is that "an index" is not one
thing: Uber built three distinct index classes — strongly consistent,
eventually consistent, and time-range — each with its own write path,
consistency guarantee, and cost profile, chosen per business use case rather
than one-size-fits-all.

It also contrasts how the *same* logical index (time-range) has to be
designed completely differently on two databases (DynamoDB vs. Uber's
Docstore) because of their partitioning behaviors, and closes with the
operational machinery — a lifecycle state machine, backfill pipeline, and
checksum validation — needed to evolve indexes safely on financial data.

## Key patterns & decisions

- **Index-intent two-phase commit**: for read-your-write indexes, write an
  index "intent" before the record, commit the intent asynchronously after
  the record lands; abort the whole insert if the intent write fails.
- **Lazy intent repair on read**: leftover intents (from failed commits or
  failed record writes) are resolved at read time — commit if the record
  exists, roll back if not — done asynchronously so reader latency is
  untouched.
- **Consistency as an explicit budget**: strong indexes cost serial write
  latency and lower availability (any intent failure fails the insert), so
  they are reserved for flows like credit-card holds; payment-history-style
  views tolerate seconds of lag and use background-built indexes instead.
- **Materialized views for eventually consistent indexes**: build them out of
  band from the online write path (via the database's CDC-driven view
  feature) so they cannot hurt write availability or latency.
- **Buffer-then-permanent dual-table design (DynamoDB)**: absorb
  wall-clock-correlated writes into a hash-bucketed write-optimized table to
  dodge hot partitions and per-partition throughput throttling, then batch-move
  entries into a time-partitioned read-optimized table and drop the buffer.
- **Fixed-shard prefix scanning (Docstore)**: with a bounded shard count and
  primary-key-sorted storage, one table partitioned on the full fine-grained
  timestamp suffices — reads do bounded scatter-gather prefix scans plus a
  sort-merge, eliminating the dual-table state machine entirely.
- **Index lifecycle state machine**: create → backfill from cold storage →
  validate → swap reads/writes to the new index → decommission the old one;
  index evolution is an orchestrated workflow, not an ad hoc migration.
- **Order-independent checksum validation**: verify backfilled indexes by
  computing aggregate checksums per time window on both the source of truth
  and the index table; a single missing entry breaks the window's checksum.
- **Rate-limited pluggable backfill**: historical processing is a reusable
  component with configurable rate limiting and batching because download
  speed outstrips processing speed.

## When to apply / trade-offs

- Use the intent/2PC pattern when a stale index can cause real-world harm
  (double-charging a card); accept that it couples index availability to
  write availability — the article is explicit that you should only pay this
  when the use case demands it.
- Timestamp-keyed writes are inherently hot-spotting on hash-partitioned
  stores whose partition count grows with data size; the mitigation you need
  depends on whether the store gives you a bounded, sorted shard layout.
- The Docstore redesign shows a database migration can *simplify*
  architecture, not just cut cost: removing the buffer-table coordination
  removed a past source of availability incidents (buffer tables not created
  in time blocked writes).
- Results cited: over 2 trillion indexes with no detected inconsistency in
  6+ months, no incidents during backfill, and roughly $6M/year saved by
  moving off DynamoDB — the consolidation argument (fewer external
  dependencies) rides along with the cost one.
- Validation-by-checksum generalizes to any large backfill or migration where
  row-by-row comparison is unaffordable.

## Fidelity check

1. Claim: strong indexes use an intent written before the record and
   committed asynchronously afterward. Support: the capture describes the
   insert starting with an index-intent write, committing intents after a
   successful record write off the latency path, and failing the entire
   insert if the intent write fails.
2. Claim: DynamoDB time-range indexes needed a two-table design because of
   hot partitions. Support: the capture explains ledger timestamps cluster
   around the current wall clock, that a hot partition triggers DynamoDB
   write throttling, and that Uber therefore buffered writes in M
   hash-buckets before batch-loading a time-partitioned permanent table.
3. Claim: index completeness is verified with time-windowed
   order-independent checksums. Support: the capture describes an offline job
   comparing aggregate checksums per time window between source-of-truth data
   and the index table, where even one missed entry causes a mismatch.
