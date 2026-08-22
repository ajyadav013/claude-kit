---
source: https://www.figma.com/blog/how-figmas-databases-team-lived-to-tell-the-scale/
author: Figma (Sammy Steele)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Figma's in-house horizontal sharding of RDS Postgres: logical-before-physical, views, and a proxy query engine

## What it teaches

Figma's database load grew about 100x in four years. Vertical partitioning (moving
related table groups onto their own Postgres instances) bought runway, but its
smallest unit is a whole table — and individual multi-terabyte, billions-of-rows
tables were hitting hard ceilings: vacuum-driven reliability risk (transaction ID
exhaustion) and RDS IOPS limits. With only months of headroom, the team chose to
build horizontal sharding *on top of* the RDS Postgres stack they already knew how
to operate, rather than migrate to NewSQL (CockroachDB/TiDB/Spanner/Vitess) or
NoSQL. The bet: a tailored, deliberately incomplete sharding layer built on deep
in-house expertise beats a more capable but unknown platform under deadline
pressure. The first sharded table shipped after roughly nine months, with about ten
seconds of partial primary unavailability at failover and no latency or
availability regressions.

The article is really a masterclass in *de-risking*: measure limits per bottleneck
to quantify runway, decompose the migration so every stage is independently
reversible, and rehearse against live production traffic before committing.

## Key patterns & decisions

- **Quantify runway per bottleneck before choosing a lever**: combine historical
  data and load tests to find per-shard limits across CPU, IO, table size, and
  write rates, so scaling work can be prioritized before it becomes an outage.
- **Buy-vs-build under time pressure favors operating expertise**: migrating to a
  NewSQL store meant a risky cross-store data migration plus rebuilding operational
  knowledge from zero; a narrower in-house layer over familiar RDS was the
  lower-variance path — with an explicit plan to re-evaluate NewSQL once runway is
  restored.
- **Ship a deliberately partial SQL surface**: no atomic cross-shard transactions,
  joins only within a colocation on the shard key — chosen by measuring what the
  application actually needs instead of chasing full compatibility.
- **Colocations ("colos") as the developer contract**: groups of related tables
  share a shard key and physical layout, so single-key cross-table joins and
  transactions still work — matching how most application code already behaved.
- **A handful of natural shard keys instead of one synthetic key**: rather than
  backfilling a composite key onto every table, nearly all tables shard by one of
  a few existing keys (user, file, or org ID).
- **Hash the shard key for routing**: existing IDs were auto-incrementing or
  timestamp-prefixed and would hotspot; hashing evens the distribution at the
  accepted cost of inefficient range scans over shard keys (rare in their
  codebase).
- **Split logical sharding from physical sharding**: make the application behave
  as if sharded (routing, constraints, semantics) while data still lives on one
  host; logical rollout is percentage-based and reverts with a config flip,
  whereas physical splits need heavyweight coordination to undo.
- **Postgres views as zero-copy logical shards**: per-shard views defined by hash
  ranges over the shard key, each fronted by its own connection pooler, let the
  system look sharded before any data moves; load tests and a shadow-read
  framework confirmed view overhead was minimal (under ten percent worst case).
- **A proxy-tier query engine (DBProxy)**: a Go service between the application
  and the connection pooler that parses SQL into an AST, extracts logical shard
  IDs (logical planner), and rewrites/routes to physical databases (physical
  planner) — also the natural home for load shedding, request hedging, and
  observability.
- **Scatter-gather as a budget, not a feature**: queries lacking a shard key fan
  out to every shard and aggregate back; each such query costs as much load as on
  an unsharded database, so the supported query subset was chosen to keep them
  rare (about 90 percent of observed queries supported).
- **Shadow planning/readiness against live traffic**: candidate shard keys were
  evaluated by running the logical planning phase in shadow on production queries
  and analyzing the logged plans offline, telling product teams exactly which call
  sites needed refactoring before anything moved.
- **Dynamic topology metadata with enforced invariants**: table-to-shard-key and
  logical-to-physical mappings live in a topology service delivering sub-second
  updates, with invariants like "each shard ID maps to exactly one physical
  database"; logical/physical separation also lets non-production mirror the
  production logical topology on far fewer machines.
- **Every stage reversible ("avoid one-way doors")**: rollback remains possible
  even after a physical shard split, and sharded/unsharded Postgres stay mutually
  compatible so unknown unknowns never strand the system.

## When to apply / trade-offs

This path suits teams with deep operational expertise in a conventional RDBMS,
tight timelines, and a workload whose query patterns concentrate on a few natural
keys. The costs are real: partial commit failures across shards must be absorbed by
product logic, foreign keys and global unique indexes lose database enforcement,
schema changes need cross-shard coordination, and the proxy query engine is a new
critical-path service that must stay simple or it converges on reimplementing the
database. If range scans on the shard key are common, hash routing is the wrong
choice. And the decision is time-indexed, not absolute — Figma itself flagged
re-evaluating managed/NewSQL options later. The transferable meta-patterns are the
logical-before-physical rehearsal, shadow traffic validation, and choosing feature
subsets from measured usage.

## Fidelity check

1. Claim: vertical partitioning could not solve their biggest tables' problems.
   Capture support: the post explains the smallest vertical-partitioning unit is a
   single table, while individual tables with terabytes and billions of rows were
   causing vacuum-related reliability risk and approaching RDS IOPS ceilings.
2. Claim: views were validated before adoption with quantified overhead. Capture
   support: they load-tested a sanitized production query corpus with and without
   views and ran a shadow-reads comparison, finding minimal overhead in most cases
   and under ten percent in the worst case.
3. Claim: the first physical failover was nearly invisible to users. Capture
   support: the first horizontally sharded table shipped in September 2023 with
   about ten seconds of partial availability on primaries, no replica availability
   impact, and no post-shard latency or availability regressions.
