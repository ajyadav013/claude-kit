---
source: https://discord.com/blog/how-discord-stores-trillions-of-messages
author: Discord
license-note: ideas absorbed in own words; no text or code reproduced
---

# Discord's trillion-message store: taming hot partitions before swapping the database

## What it teaches

By early 2022 Discord's message cluster had grown from 12 Cassandra nodes
(2017, billions of messages) to 177 nodes holding trillions, and it had become
an operational tar pit: unpredictable latency, compaction backlogs, JVM GC
pauses needing manual node babysitting, and a recurring ritual of rotating
nodes out of traffic just to let them compact. The deep lesson is that they
did NOT treat a database swap as the whole fix. They first built a protective
service layer that bounded concurrency toward the storage tier, and only then
migrated to ScyllaDB (a C++ Cassandra-compatible engine with no garbage
collector and shard-per-core isolation) — after waiting for the vendor to fix
a specific blocker, slow reverse-order scans. The cutover in May 2022 shrank
the fleet from 177 nodes to 72 larger ones and collapsed tail latencies
(historical-read p99 from a 40-125ms band to ~15ms; insert p99 from a 5-70ms
band to a steady 5ms), and the system absorbed the World Cup final traffic
spikes without drama.

## Key patterns & decisions

- **Partition by natural conversation unit plus time bucket**: messages keyed by channel and a fixed time window, with chronologically sortable snowflake IDs — locality for the dominant read pattern, bounded partition size.
- **Hot-partition failure mode**: wildly skewed channel activity plus read-heavier-than-write LSM storage means one busy partition degrades whole-node latency, and quorum reads spread that pain cluster-wide.
- **Request coalescing in a data-service tier**: a thin gRPC-per-query intermediary (no business logic) merges concurrent identical reads into one database query — the first caller spawns a worker task, later callers subscribe to its result.
- **Consistent-hash routing keyed on the partition key**: routing all requests for a channel to the same data-service instance maximizes coalescing hit rate; the shield works because routing and coalescing compose.
- **Shield first, migrate second**: the data services bought breathing room on the ailing cluster, decoupling the emergency from the migration timeline.
- **Hold the riskiest migration for last, and remove known blockers**: every other cluster moved to ScyllaDB by 2020; messages waited until reverse-query performance was fixed upstream and the team had production experience with the new engine.
- **Build the migrator on proven internal libraries**: dual-write to both stores, then a custom Rust migrator (token-range reads, local SQLite checkpointing, bulk writes) cut the estimated backfill from three months (stock Spark migrator) to nine days at up to 3.2M messages/sec — which in turn let them drop a more complex time-split cutover plan for a single flip.
- **Validate by shadow-comparing reads**: a small slice of production reads went to both databases with results diffed before trusting the new store.
- **Storage topology trick**: local SSDs RAID-mirrored onto persistent disk to get local-disk speed with durable-disk safety.

## When to apply / trade-offs

- The data-service pattern applies whenever read skew (celebrity/announcement effects) can hotspot storage: bounding concurrency upstream is cheaper than overprovisioning the database. It costs an extra network hop and a new fleet to operate.
- Coalescing plus keyed routing only pays off when many concurrent requests are truly identical (same row); for diverse reads it adds latency without benefit.
- A GC-free engine removed a whole class of operational toil, but the team explicitly expected no magic: hot partitions survive a database swap, which is why the upstream shield mattered.
- The migration sequencing (dual-write, backfill newest-first was abandoned once backfill got fast enough, shadow reads, rehearsed flip) is a reusable zero-downtime playbook; note the last 0.0001% stalled on uncompacted tombstone ranges — dirty legacy data is a predictable end-of-backfill hazard.

## Fidelity check

1. Claim: the fleet shrank while per-node capacity grew. Support: the capture states 177 Cassandra nodes were replaced by 72 ScyllaDB nodes, each carrying 9TB of disk versus roughly 4TB average before.
2. Claim: the custom Rust migrator was dramatically faster than the off-the-shelf path. Support: the tuned Spark-based migrator projected about three months; the extended in-house data-service library finished in about nine days, peaking at 3.2 million messages migrated per second.
3. Claim: coalescing works by subscription to an in-flight query. Support: the article describes the first request spinning up a worker task, subsequent identical requests finding and subscribing to that task, and one database read fanning results back to all subscribers.
