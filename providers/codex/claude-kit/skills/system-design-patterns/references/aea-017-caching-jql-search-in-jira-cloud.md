---
source: https://www.atlassian.com/blog/atlassian-engineering/reducing-jql-database-load-with-caches
author: Atlassian
license-note: ideas absorbed in own words; no text or code reproduced
---

# Caching an uncachable query language: four iterations of the JQL Subscription Service

## What it teaches

Jira Cloud's per-tenant Postgres databases were maxing out the largest available RDS instances,
driven largely by JQL (Jira's SQL-ish issue query language) — a single innocuous-looking query
can expand to ~100 lines of SQL joining ~26 tables, and product surfaces like Service Management
queues poll the same queries every few seconds. Rather than adding read replicas (expensive, and
the legacy monolith assumes strong consistency), the team chose to shrink database load with a
purpose-built cache. The article walks honestly through four design iterations, each one exposing
why the previous "done" design wasn't, which makes it a case study in evolving a cache against a
query language that is per-user, time-dependent, and permission-aware.

## Key patterns & decisions

- **Naive read-through caching fails for dynamic queries.** A plain results cache with
  event + TTL invalidation cannot handle per-user functions (whose result depends on who asks),
  time-relative clauses (whose result depends on when asked), permission differences between
  users, or the many syntactically different spellings of the same query.
- **Query splitting.** Parse and normalize the query, then divide it: a "Stage 1" part holding
  only static, user- and time-independent clauses (cacheable), and a "Stage 2" part holding the
  dynamic clauses plus ordering (executed fresh per request, constrained to the Stage 1 result
  set via a key-membership predicate). Dynamic clauses can sometimes be widened into static
  placeholder filters to keep Stage 1 selective.
- **Push permission-sensitive clauses to the per-request stage.** Because Stage 2 always runs as
  the actual user, running Stage 1 without permissions is safe; the one field type whose
  visibility varies per-clause (comments) is deliberately routed into Stage 2.
- **Decouple invalidation from refresh.** Issue-change events arrive faster than reads, so
  instead of refreshing on every event, an event merely sets a dirty flag; the next user read
  observes the flag and triggers a refresh. No reader, no work.
- **Distributed per-query lock + stale-while-revalidate.** Slow cache population (one production
  example took ~30 seconds) invites stampedes, so a distributed lock allows one population at a
  time, and readers are served the existing stale entry while the refresh runs asynchronously on
  a different node via a message queue — trading consistency for latency and moving heavy work
  off user-facing request threads.
- **A version endpoint instead of query execution.** Pollers mostly want to know "did anything
  change?"; exposing a monotonic version of the cached subscription lets clients skip executing
  even the cheap Stage 2 query on the common no-change poll.
- **Bound what you cache.** Store only issue IDs (hydration is another service's job), and cap
  the cached result-set size rather than engineering around the driver's ~32k-value limit on IN
  clauses — accept a limit, roll out progressively.
- **Coarse event matching.** Instead of understanding every field and event type, extract a small
  set of commonly queried fields (project, type, status, sprint) as metadata per query and mark
  the query dirty on any event touching those; over-invalidation is accepted, with a backup
  staleness TTL catching everything else.
- **A layered short-TTL per-user cache** (about five seconds, events + TTL) sits on top for
  frequently re-polled Stage 2 results — the "iteration 1" design reappears, correctly scoped.
- **Define the success metric first.** They approximated database load by query execution time as
  seen from the calling code and normalized it per user (DBLoadPerUser) so a big win for one
  tenant couldn't hide a regression for another.

## When to apply / trade-offs

- Splitting is the reusable move whenever queries mix expensive-but-static filters with
  cheap-but-dynamic ones (personalization, time windows, ACLs): cache the static core, re-apply
  the dynamic remainder per request.
- Every iteration trades consistency for load: stale reads, dirty-flag refresh, 5-second TTLs,
  and version polling all widen the eventual-consistency window — acceptable here because queue
  UIs tolerate ~10 seconds of lag, not acceptable for read-after-write paths.
- Coarse event matching over-invalidates; finer matching would cut refreshes further but costs a
  model of every field type. Start coarse with a TTL backstop.
- Results: rollout to the queues surface cut DBLoadPerUser by roughly 77% overall and improved
  the backing REST APIs by ~81% (~4 s) at p90, with no per-customer regressions observed.

## Fidelity check

1. Claim: JQL queries are deceptively expensive at the SQL level. Support: the capture gives an
   example where a short JQL filter compiles to roughly 100 lines of SQL joining 26 tables, and
   notes queues re-poll such queries every few seconds.
2. Claim: refresh is triggered by reads, not events. Support: the capture describes the chosen
   "update on stale read" scheme — an event sets a flag in the cache, and the next read performs
   the refresh, clearing the flag if no further events arrived.
3. Claim: the service produced a large measured load reduction. Support: the capture reports a
   76.6% reduction in the DBLoadPerUser metric for the queues experience (including staging and
   internal instances) and an average 81% p90 latency improvement in the queue-backing APIs.
