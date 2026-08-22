---
source: https://algomaster.io/learn/system-design/indexing
author: AlgoMaster
license-note: ideas absorbed in own words; no text or code reproduced
---
# Database indexes: query-first design, selectivity, and the write-cost ledger

## What it teaches
An index is an auxiliary structure — typically a sorted B-tree keyed on chosen
columns with pointers back to rows — that lets the engine jump near the target
instead of scanning the table. The chapter's central discipline is to design
indexes from the queries the application actually runs, not from the table's
column list, and to keep a ledger of what each index costs in storage, write
amplification, cache pressure, and migration time. It surveys the index-type
toolbox (B-tree, composite, covering, unique/clustered, hash, bitmap, partial,
expression, full-text/spatial/inverted/block-range) and repeatedly says the same
thing about all of them: confirm with the query plan, because an index the
planner never uses is pure overhead.

## Key patterns & decisions
- **Selectivity determines usefulness**: an index pays off when the filter
  narrows the search to a small fraction of rows — unique emails index well, a
  lone boolean flag barely helps, and low-cardinality columns earn their keep
  only inside composite or filtered indexes.
- **Two-phase lookup mental model**: search the index for matches, then fetch
  rows by reference — unless the index alone answers the query; small tables may
  scan faster than they seek, so index benefit is size- and stats-dependent.
- **B-tree as the general-purpose default**: sorted keys serve equality, range,
  ORDER BY, and prefix matching, and wide shallow nodes keep lookups to a few
  page reads even at huge row counts.
- **Composite-index column ordering rule of thumb**: equality-filtered columns
  first, then range filters, then sort columns; the same columns in a different
  order serve different queries, and the plan (EXPLAIN) is the arbiter.
- **Covering index / index-only scan**: include every column a hot query needs
  so the engine can skip the table fetch entirely — but wider indexes cost more
  disk, cache, and write work, so reserve them for measured, frequent queries.
- **Clustered layout is engine-specific**: some engines make the clustered index
  the table itself, others cluster by primary key, and others offer only a
  one-time rewrite whose ordering decays with new writes; sequential vs random
  key choice changes write scatter.
- **Specialized indexes for non-B-tree shapes**: hash for pure equality (no
  ranges or ordering), bitmap for low-cardinality analytics filters combined
  with AND/OR (poor under heavy writes), partial indexes for the active subset
  of a table, expression indexes when queries wrap a column in a function that
  would otherwise disable index use, and full-text/spatial/inverted/block-range
  structures for text, geo, document, and append-only-log workloads.
- **Every index is a standing write tax**: inserts/updates/deletes must maintain
  each index, hot indexes compete for memory, and building one on a big table
  is itself a costly migration — so production systems should actively hunt
  unused and duplicate indexes for removal.
- **Query-first checklist**: for each important query, identify the filter,
  join, sort, and selected columns plus run frequency and column volatility,
  derive the index from that, then verify the planner adopts it.

## When to apply / trade-offs
Use the checklist whenever a slow query appears or a new access path ships, and
run the anti-pattern list in review: piles of single-column indexes where one
composite would serve, wrong composite ordering, standalone low-selectivity
indexes, functions applied to indexed columns without an expression index,
expecting a B-tree to accelerate an infix wildcard search, assuming LIMIT is
cheap without a supporting index, and never rechecking the plan after changes.
The persistent trade-off: each read speedup is bought with write and storage
cost, so indexes on frequently mutated columns and wide multi-column indexes
need stronger justification than narrow indexes on stable, selective columns.

## Fidelity check
1. Claim: the chapter grounds index value in selectivity. Support: the capture
   tabulates example columns from unique email (high selectivity, very useful)
   down to a boolean deleted flag (very low, weak alone) and says low-cardinality
   columns may still help within multi-column or filtered indexes.
2. Claim: it gives a composite-ordering heuristic with a verification step.
   Support: the capture recommends equality filters first, then ranges, then
   ordering columns, labels this a starting point rather than a law, and says to
   confirm with a plan tool such as EXPLAIN.
3. Claim: it frames indexes as ongoing costs needing cleanup. Support: the
   capture lists storage, slower writes, memory competition, migration time, and
   planner overhead as per-index costs and says production systems should track
   unused and duplicate indexes.
