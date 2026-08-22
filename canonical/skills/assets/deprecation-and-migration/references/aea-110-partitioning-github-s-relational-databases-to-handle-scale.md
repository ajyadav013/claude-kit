---
source: https://github.blog/engineering/infrastructure/partitioning-githubs-relational-databases-scale/
author: GitHub
license-note: ideas absorbed in own words; no text or code reproduced
---

# GitHub: lint your way to virtual partitions, then cut over in milliseconds

## What it teaches
GitHub's core features all lived in one MySQL cluster, so any incident there was an
everything-incident, and hardware upsizing was the only lever left. Their partitioning
program inverted the usual order: first make the split real in the application layer
(virtual partitioning enforced by linters), and only then move bytes — using two
independent mechanisms, Vitess and a home-grown replication-based write-cutover. The
payoff was halved per-host load and fewer database incidents while overall query volume
kept growing.

## Key patterns & decisions
- Virtual partitioning before physical partitioning: declare "schema domains" — sets of
  tables that are legitimately queried and transacted together — in a checked-in YAML
  config, and force every table to belong to exactly one domain.
- Query linter in dev/test/CI: any SQL statement touching tables from two domains raises an
  explanatory error at development time, so new cross-domain coupling cannot creep in
  unnoticed.
- Escape hatch that doubles as a work queue: a special SQL comment annotation suppresses
  the linter, and the set of annotated queries becomes the measurable backlog of couplings
  still to untangle.
- Transaction linter sampled in production: cross-domain transactions (which would lose
  atomicity after a split) are found by lightweight sampling of live traffic, then either
  the code path is changed or the data model is reshaped.
- Replace database joins with application-side composition: split one join into two keyed
  queries and merge in Ruby; they upstreamed ORM support to Rails (an option on
  associations that avoids JOINs across underlying tables) — and occasionally the app-side
  join even beats the database planner's unstable execution plans.
- Duplicate-and-localize polymorphic tables: shared catch-all tables (e.g., one table of
  reactions spanning many features) get extracted into per-domain tables so transactional
  guarantees survive the move.
- Guard performance-sensitive rewrites with dual-run experiments: old and new
  implementations execute side by side on a slice of production traffic before switching.
- Keep two independent migration tools: Vitess vertical sharding (proxy processes speaking
  the MySQL wire protocol, replication underneath) and a bespoke cutover script — so no
  single unproven tool gates availability.
- The write-cutover recipe: make the destination cluster a replication sub-tree of the
  source, front both with a routing proxy, then briefly set the source read-only, record
  its last transaction ID, wait until the destination has replayed it, detach replication,
  flip the proxy routing, and re-enable writes — measured in tens of milliseconds for the
  hottest tables, run at the daily traffic trough.
- Prefer proven, "boring" technology plus small application changes over exotic
  re-platforming when reliability is the primary constraint.

## When to apply / trade-offs
- The linter-first approach suits large monolithic codebases where nobody knows all the
  hidden cross-feature couplings; it converts an unknowable migration risk into a countable
  exemption list.
- Accepting a brief global write-freeze (failed writes surface as user-facing errors for a
  moment) buys enormous simplicity versus fully online cutover machinery; viable only if
  the freeze is truly tens of milliseconds and scheduled at low traffic.
- Splitting domains sacrifices cross-domain transactions and joins forever after; the
  polymorphic-table extraction pattern is the tax paid to keep the guarantees that matter.
- Running two migration mechanisms costs engineering effort but hedges against a single
  tool's immaturity — a deliberate risk-mitigation redundancy.

## Fidelity check
1. Claim: the cutover freeze is measured in tens of milliseconds. Capture support: the post
   reports the six-step cutover script completing in a few tens of milliseconds even for
   the busiest tables, causing only a handful of failed writes.
2. Claim: load per host halved despite traffic growth. Capture support: in 2019 the single
   cluster averaged about 950k queries/s; by 2021 the same tables spread over several
   clusters served about 1.2M queries/s while average per-host load dropped by half.
3. Claim: the biggest single move covered GitHub's core tables. Capture support: the
   custom write-cutover was used to move 130 of the busiest tables at once — those backing
   repositories, issues, and pull requests.
