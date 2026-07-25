---
source: https://www.figma.com/blog/how-figma-scaled-to-multiple-databases/
author: Figma
license-note: ideas absorbed in own words; no text or code reproduced
---

# Figma: vertical partitioning as the pragmatic road out of a single overloaded Postgres

## What it teaches
Figma's traffic to its lone RDS Postgres instance was tripling yearly and peak CPU was
climbing past 65%, so the infra team had to buy headroom without downtime for a real-time
collaboration product. After evaluating horizontal sharding options (NoSQL rewrite, Vitess,
distributed-Postgres NewSQL, self-hosting) they rejected all of them — either too much
application rework, too much first-customer risk on unproven managed offerings, or too much
new operational burden — and instead split groups of tables into separate Postgres databases
(vertical partitioning). The article walks through how they picked which tables to move, and
the near-zero-downtime cutover machinery they built to move them repeatedly in production.

## Key patterns & decisions
- Buy tactical runway first: max out the instance size, add read replicas, route brand-new
  features to fresh databases, and put a connection pooler (PgBouncer) in front — cheap moves
  that defer, but do not solve, the scaling problem.
- Reject the biggest-hammer option deliberately: they chose not to be the largest early
  adopter of a managed distributed-Postgres product, treating "first customer at this scale"
  as an unacceptable risk category of its own.
- Vertical partitioning as a stepping stone: moving whole table groups to their own databases
  relieves load now and builds the exact tooling later needed for horizontal sharding of the
  few tables that will individually outgrow one machine.
- Pick partition candidates on two axes: impact (measured as average active sessions per
  table, derived from sampling Postgres activity views at 10 ms intervals) and isolation
  (how few joins, foreign keys, and cross-table transactions the group participates in).
- Instrument the ORM at runtime instead of trusting static analysis: dynamic Ruby/ActiveRecord
  code hides which physical tables a query touches, so they shipped runtime validators that
  stream real production query/transaction shapes into their data warehouse to find
  co-accessed table clusters.
- Split the proxy layer before splitting the data: creating separate PgBouncer pools that
  still point at the same database lets misrouted client traffic be detected harmlessly
  before the real data move, shrinking the blast radius of the risky step to a handful of
  proxy nodes instead of thousands of app servers.
- Use logical (not streaming) replication so the destination holds only the moving subset,
  can run a different Postgres major version, and can host a reverse replication stream back
  to the source as an undo path.
- Drop indexes on the destination and rebuild them after the bulk copy: logical replication's
  row-at-a-time index maintenance turned a terabyte-scale copy into a multi-week job; copying
  index-free and rebuilding cut it to hours.
- Prove synchronization with WAL positions before the switch: capture the source's log
  sequence number after writes stop, wait until the destination has replayed past it, and
  only then promote — an explicit no-data-loss gate.
- Design the cutover for repeatability and reversal: sub-minute availability budget,
  automated procedure, and a rollback path were explicit acceptance criteria, and the
  operation was rerun many times (2 tables in the first run, 50 in the last).

## When to apply / trade-offs
- Fits teams on a mature single relational database facing growth, where a full re-platform
  is riskier than living without cross-database joins, foreign keys, and multi-table
  transactions for the moved groups.
- The cost lands on application developers: every strongly-coupled table group is expensive
  to move, which is why the isolation metric drives candidate choice.
- Vertical partitioning has a ceiling — a single hot, huge table still saturates its own
  machine — so it defers rather than replaces horizontal sharding.
- Multiplying databases multiplies routing knowledge in clients; Figma followed up with a
  central query-routing service to contain that complexity.

## Fidelity check
1. Claim: they saw roughly a half-minute of partial impact per move. Capture support: each
   production partitioning operation showed about a 30-second window where roughly 2% of
   requests were dropped.
2. Claim: index handling was the key to fast initial copies. Capture support: the post
   attributes slow logical-replication copies to one-row-at-a-time index updates on the
   destination, and says removing then rebuilding indexes brought copy time from potentially
   weeks down to hours.
3. Claim: the effort produced large headroom. Capture support: after the operations, the
   busiest partition sat near 10% CPU utilization, versus the pre-project single database
   exceeding 65% at peak, and some low-traffic partitions were even downsized.
