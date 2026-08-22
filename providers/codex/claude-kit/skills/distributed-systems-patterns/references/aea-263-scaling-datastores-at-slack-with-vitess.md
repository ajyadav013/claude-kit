---
source: https://slack.engineering/scaling-datastores-at-slack-with-vitess/
author: Slack Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Escaping tenant-sharding limits by adopting a sharding middleware (Slack's Vitess migration)

## What it teaches

Slack began as a LAMP monolith with all data in MySQL, sharded by workspace:
a metadata cluster mapped workspace to shard, a "kitchen sink" cluster held
non-tenant data, and each shard ran two MySQL primaries in different
datacenters replicating to each other (active-active). The application itself
did the routing. This bought early wins — either primary could serve
reads/writes so failover was invisible, the everything-for-one-tenant-on-one-
host model was intuitive for feature teams, debugging was fast, and growth
meant just adding shards.

The model broke on four fronts as the company scaled. Biggest tenants outgrew
the largest available hardware — a hard per-tenant ceiling. New products
(Enterprise Grid, Slack Connect) violated the assumption that one tenant's
data lives on one shard. Load became lumpy: a few enterprise-customer hot
spots while an over-provisioned long tail idled, because moving tenants
between shards was hard. And one shard's outage was a total Slack outage for
every tenant on it, with no workload isolation. The bespoke topology also
blocked safe use of read replicas.

The pivotal decision was evolve-versus-replace. They ruled out NoSQL
(DynamoDB, Cassandra) and NewSQL (Spanner, CockroachDB) because thousands of
existing queries used MySQL-specific constructs and years of operational
practice (backup, ETL, compliance) were MySQL-shaped. They also prototyped
building the new sharding logic into the application and rejected it: routing
was already tangled with product logic (e.g., message counts hard-wired to
team-locality assumptions), and an app-layer solution fixed neither
operations nor replica usage, and would hit the same wall again on a hot
write path. Vitess won because it keeps MySQL as the storage engine while
moving sharding, topology, failover, and backups into a dedicated layer the
application can be ignorant of.

Adoption was deliberately incremental: a first end-to-end production use case
on a deliberately small feature (RSS-feed ingestion into channels) forced all
the operational plumbing — provisioning, discovery, backup/restore, topology,
credentials — to be built for real. Data moved via a generic backfill with
application double-writes, verified by a parallel double-read diffing system
before cutover. Gaps in Vitess were closed by contributing upstream (query
compatibility, topology scalability, migration and load-test tooling,
Prometheus/Orchestrator/xtrabackup integration) rather than forking. Three
years in, 99% of query traffic (2.3M QPS peak, 2ms median / 11ms p99) ran on
Vitess. Resharding by finer keys (e.g., channel ID instead of workspace)
erased the hot spots, and the flexible layer paid unplanned dividends: a 50%
one-week query surge in March 2020 was absorbed by splitting a busy keyspace,
and international data residency shipped quickly because region placement was
abstracted away from product code.

## Key patterns & decisions

- Tenant-sharding has a hard ceiling: when the largest tenant exceeds the largest host, per-tenant sharding is dead — reshard by a finer-grained entity key to spread load.
- Evolve, don't replace, the storage engine: keeping MySQL underneath preserved thousands of queries and years of operational practice, ruling out NoSQL/NewSQL rewrites.
- Sharding belongs in a dedicated layer, not the application: app-layer routing couples product logic to data placement and never fixes operations, replicas, or topology management.
- Prove a new datastore with one small end-to-end production feature: the pilot forces every operational integration (provisioning, discovery, backup, credentials) to exist before mass migration.
- Backfill + double-write + double-read diffing: clone tables while the app writes to both systems and compare read results in parallel to prove semantic equivalence before cutover.
- Contribute gaps upstream instead of forking: closing missing functionality in the open-source project made the community an extension of the team and kept the fork cost at zero.
- Hot spots plus an idle long tail signal a sharding-key problem, not a capacity problem — over-provisioning is the symptom tax.
- Shared-blast-radius awareness: one-shard-per-tenant means a shard outage is a full product outage for those tenants; workload isolation should be a design goal.
- Flexible infrastructure pays unplanned dividends: the same layer later carried new services, a 50% pandemic surge, and multi-region data residency none of which drove the original decision.
- Declare victory slowly: they waited until 99% migrated (three years) before publishing the success story.

## When to apply / trade-offs

This is the canonical decision framework for a datastore at its scaling
ceiling: enumerate what your ecosystem is shaped around (query dialect,
tooling, compliance, muscle memory) before entertaining a storage-engine
swap; the cheapest path usually keeps the engine and replaces the routing
layer. Budget realistically — this was a multi-year, whole-team effort with
significant upstream contribution, justifiable only for a mission-critical
store. The double-write/diff verification pattern generalizes to any live
data migration. Beware the seductive middle option (build sharding into the
app): it looks cheapest, but Slack's prototyping showed it re-creates the
same coupling and operational gaps one layer up.

## Fidelity check

1. Claim: the old model imposed a hard per-tenant ceiling. Capture states
   that as larger customers onboarded, their designated shard hit the largest
   available hardware and regularly ran at the limit of what a single host
   could sustain.
2. Claim: migration correctness was proven with dual writes and comparison
   reads. Capture describes a generic backfill system cloning tables under
   application double-writes plus a parallel double-read diffing system to
   confirm the Vitess tables behaved identically to the legacy databases.
3. Claim: the flexible sharding layer absorbed the pandemic surge. Capture
   reports query rates rising 50% in one week in March 2020 and Slack scaling
   a hot keyspace horizontally with Vitess splitting workflows, which the old
   architecture could not have done for the largest customers.
