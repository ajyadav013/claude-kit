---
source: https://shopify.engineering/horizontally-scaling-the-rails-backend-of-shop-app-with-vitess
author: Shopify Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Migrating a mature Rails/MySQL backend onto sharded Vitess in three phases

## What it teaches

The Shop app outgrew a single MySQL after exhausting the usual escape valves
(scaled job system, caching, message bus, splitting tables across federated
databases). Multi-terabyte disks, week-long schema migrations, and throttled
background jobs forced a real sharding decision. The team compared multi-tenant
pod architecture, key-value offload, federation, and cloud-managed stores, then
chose Vitess for SQL compatibility, resharding, coordinated cross-shard
migrations, and connection pooling. The article is a detailed field report of
the three-phase migration and the tooling that made it safe.

## Key patterns & decisions

- **Pick the sharding key first, and early.** user_id was the natural key, but
  much data hung off intermediate entities and lacked the column; adding and
  backfilling user_id across billion-row tables on a saturated database took
  far longer than expected. Their strongest lesson: choose the key early and
  lint that every new table carries it non-nullable from day one.
- **Constrain the model for reasonability.** Vitess permits multiple sharding
  keys per keyspace; they deliberately allowed only user-owned tables in the
  sharded keyspace, keeping the system testable and easy to reason about.
- **Application-layer query verifiers were the single biggest success factor.**
  Five checks: sharded-table queries missing the sharding key; transactions
  spanning databases; transactions spanning shards; non-transactional
  multi-row writes crossing shards; and joins crossing keyspaces. Verifiers
  could model the *future* topology (a keyspace not yet split, a keyspace not
  yet sharded), so violations surfaced long before the risky operation.
- **Log-first verifier rollout.** Enforce in dev/test and CI (including a
  parallel CI lane running against Vitess), keep a known-violations list so new
  code is held to the bar immediately while old violations burn down, then run
  production in log-only mode with a weekly violations report. Explicit
  escape-hatch helpers exist for legitimate cross-shard maintenance work.
- **Ban cross-shard transactions outright.** Vitess's default atomicity lets a
  multi-shard transaction commit on one shard and fail on another without
  rollback; they removed every such transaction, restricting writes to one
  user's shard. Flows that changed a row's sharding key were rewritten as
  insert-in-destination then delete-in-source.
- **Three-phase migration, each phase reversible and rehearsed.** Phase 1
  "Vitessify": wrap the existing MySQL as a single unsharded keyspace behind
  the Vitess proxy — zero downtime, app-transparent, no data movement. Phase 2:
  split tables into users / global / configuration keyspaces via the built-in
  table-move workflow. Phase 3: shard the users keyspace after sequences and
  lookup indexes were in place.
- **Staged connection cutover starting with retry-safe traffic.** A dynamic
  switcher routed a controllable percentage of connections through the new
  proxy, beginning with background jobs that auto-retry, so early failures
  could not lose data.
- **Cross-shard auto-increment via sequence tables with block caching.** An
  unsharded coordinator table hands out ID blocks (cache of 1000) to tablets —
  sized to keep the coordinator off the hot path yet bound the IDs lost on
  restart. Adopting sequences on live tables required carefully setting the
  next-ID above each table's current max plus a buffer, then flipping the
  schema mapping. MySQL's own auto-increment was later dropped entirely to
  eliminate a low-probability failure mode of the two mechanisms disagreeing.
- **Avoid lookup vindexes unless truly needed.** They enforce global uniqueness
  and cut scatter queries, but slow writes and force non-transactional tests
  (a same-transaction insert-then-update on a consistent-lookup column is
  unsupported). Two free alternatives: collision-safe random keys (UUIDs), or
  composite unique indexes that include the sharding key — per-shard
  uniqueness then implies global uniqueness because a tenant lives entirely on
  one shard.
- **Rehearse in staging with bail-out checklists.** Two staging environments,
  every step practiced, a checklist including abort commands; rehearsal
  surfaced Vitess bugs, stale-artifact cleanup needs, and around 25 total bugs
  across Vitess, application, and infra layers during the sharding push.
- **Verify moves with data diffs, expect replication ordering hazards.** After
  copying, table diffs validated integrity; post-cutover, reverse replication
  broke on a uniqueness collision because update→insert→delete sequences from
  *different* shards can arrive reordered — cross-shard event ordering is not
  guaranteed.
- **Sharded schema-migration hygiene.** Shards finish migrations at different
  times, so added/removed columns go into the ORM's ignored list until all
  shards converge, and only one migration runs per keyspace at a time. A
  background job polls migration status across shards before dumping the
  schema cache, since asking a random shard mid-migration yields an
  inconsistent schema.

## When to apply / trade-offs

- The decision matrix (tenant pods vs. KV offload vs. federation vs. managed
  cloud vs. Vitess) turns on tenant-size distribution, SQL dependence, and
  whether you run your own datastores; Shop's many-small-users profile
  inverted Shopify's own few-big-merchants pod choice.
- Federation is a legitimate intermediate step — it bought them years — but
  its end state (slow migrations, no efficient cross-DB joins, app-visible
  placement) is precisely what pushed them onward.
- Vitess costs a real complexity budget: developers must learn sequences,
  vindexes, and keyspace schemas, roughly comparable to needing to understand
  indexes on plain MySQL.
- ORM patches to thread the sharding key into updates, deletes, locks, and
  association queries were accepted as temporary debt, planned for deletion
  once the framework's composite-key support landed.
- The payoff they report: schema migrations in hours instead of weeks, no more
  capacity throttling, and scaling by simply adding shards.

## Fidelity check

1. Claim: query verifiers are credited as the decisive success factor.
   Support: the capture states that if one single thing could be credited for
   the successful move, it would be the correctness of the verifiers, and the
   lessons section urges heavy investment in them.
2. Claim: they eliminated cross-shard transactions because Vitess would not
   roll back a partial commit. Support: the capture explains that with the
   default atomicity model, a transaction committing on one shard and erroring
   on a second leaves the first shard's change in place, so all cross-shard
   transactions were removed.
3. Claim: reverse replication after cutover failed due to cross-shard event
   reordering. Support: the capture reports a duplicate-key error roughly an
   hour after switching writes, caused by an update/insert/delete flow whose
   rows landed on different shards, with no ordering guarantee between events
   from different shards — mitigable but not eliminable.
