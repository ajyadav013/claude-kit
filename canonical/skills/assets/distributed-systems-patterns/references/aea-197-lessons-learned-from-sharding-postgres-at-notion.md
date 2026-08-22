---
source: https://www.notion.com/blog/sharding-postgres-at-notion
author: Notion
license-note: ideas absorbed in own words; no text or code reproduced
---

# Sharding a Postgres monolith by tenant: scheme design and a four-phase migration

## What it teaches

How Notion split one overloaded Postgres instance into 32 physical databases
holding 480 logical shards, why they chose application-level routing over
packaged sharding middleware, how they executed the cutover with only minutes
of downtime, and which decisions they would change in hindsight.

## Key patterns & decisions

- **Concrete shard trigger, not vibes.** The forcing function was operational:
  autovacuum stalling so dead tuples were never reclaimed, with transaction-ID
  wraparound (Postgres freezing all writes) looming as an existential risk.
  Soft limits like these arrive well before hardware ceilings do.
- **Application-level sharding over Citus/Vitess-style middleware.** They wanted
  transparent control over data placement; packaged clustering hid the
  distribution logic. Alternatives like a NoSQL migration or bare-metal NVMe
  Postgres were weighed and rejected on risk and maintenance grounds.
- **Shard the transitive foreign-key closure of the hot table.** Everything
  reachable from the block table via relationships moved together, because a
  row living in a different physical database than its related block breaks
  single-host transactionality (e.g., a block deletion committing while the
  dependent comment update fails).
- **Tenant ID as partition key.** Every sharded row belongs to exactly one
  workspace, and queries overwhelmingly stay inside one workspace, so
  partitioning by workspace UUID avoids most cross-shard joins. A footnote
  warns that sharding by the wrong entity (e.g., by user before pivoting to a
  team product) bakes a product assumption into the architecture.
- **Pick a shard count with many divisors.** 480 logical shards divide evenly
  across 32, 40, 48, 60... hosts, allowing incremental host additions. A
  power-of-two count would force doubling the fleet at every rebalance.
- **Logical shards as plain schemas, routed in the app.** Fifteen schemas per
  physical database, each holding one copy of every sharded table. They chose
  separate per-schema tables over native partitioned tables so one lookup in
  application code maps workspace ID straight to database + schema, keeping a
  single source of routing truth.
- **Four-phase migration playbook: double-write → backfill → verify → switch.**
  Generic enough that they present it as their standard framework for any data
  migration.
- **Audit-log double-writing.** Direct dual writes were judged too flaky
  (inconsistency on partial failure) and Postgres logical replication could not
  keep pace with the block table's write volume during the initial snapshot;
  instead an audit table recorded writes and a catch-up process replayed them
  onto the shards. A reverse audit log was prepared as a rollback path.
- **Idempotent, version-aware backfill.** The backfill compared record versions
  and skipped rows already newer on the target, so backfill and catch-up could
  run in any order and converge.
- **Layered verification with adversarial separation.** Sampled UUID-range
  comparisons plus "dark reads" (fetching from both stores, serving the old,
  logging diffs) — and deliberately having different people implement migration
  and verification so a shared bug could not silently pass both.
- **Hindsight lessons.** Shard before the monolith is strained (they could not
  even backfill the partition-key column in place); optimize the catch-up
  window enough to hot-swap with zero downtime; fold partition key and primary
  key into one column instead of threading a separate partition key through the
  whole application.

## When to apply / trade-offs

- Vertical scaling ends before the hardware limit: query planning and
  maintenance processes degrade first. Watch vacuum health and TXID age as
  leading indicators.
- Application-level sharding buys placement control at the cost of building
  routing, rebalancing, and migration tooling yourself — the opposite trade of
  adopting Vitess/Citus.
- Waiting too long removes options: every migration technique that adds load to
  the struggling primary (logical replication, in-place backfills) becomes
  unavailable exactly when you need it.
- Tenant-keyed sharding assumes tenant-scoped access patterns; heavy cross-
  tenant queries would erase the benefit.

## Fidelity check

1. Claim: the migration trigger was vacuum stall with TXID wraparound as the
   feared endpoint. Support: the capture says the inflection point was the
   VACUUM process consistently stalling, and that wraparound — where Postgres
   stops accepting writes to protect data — was seen as an existential threat.
2. Claim: 480 was chosen for divisibility, enabling incremental host scaling.
   Support: the capture lists 480's many factors, contrasts with 512 whose
   power-of-two factors would force jumps from 32 straight to 64 hosts, and
   explicitly advises picking values with many factors.
3. Claim: migration and verification were written by different people on
   purpose. Support: the capture states this precaution existed because one
   person implementing both stages could repeat the same error in both,
   undermining the point of verification.
