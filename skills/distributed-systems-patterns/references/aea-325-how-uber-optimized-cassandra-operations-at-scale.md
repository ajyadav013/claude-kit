---
source: https://www.uber.com/en-IN/blog/how-uber-optimized-cassandra-operations-at-scale/
author: Uber Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Running Cassandra as a managed fleet: how small operability fixes compound into reliability

## What it teaches

Uber has operated Cassandra as an internal managed service since 2016 —
tens of thousands of nodes, hundreds of clusters, millions of QPS — with a
central team owning the control plane, forked clients, on-call, and even data
modeling guidance for customer teams. The article is a debugging travelogue:
three chronic production pain points (node replacement failures, flaky
lightweight transactions, sluggish anti-entropy repair) and how each was fixed
with targeted, mostly small changes to Cassandra internals and the
surrounding control plane. Its stated thesis is that incremental fixes
compound: at fleet scale, even a 5% failure rate on routine operations
translates into multiple full-time engineers doing manual recovery, so
operability defects are capacity problems.

## Key patterns & decisions

- **Managed-service operating model**: one platform team owns the database
  end to end (features, upstream contributions, control plane integration,
  observability, 99.99% availability, best-practice consulting) so hundreds
  of product teams don't each run their own.
- **Control-plane-orchestrated lifecycle**: an in-house stateful platform
  (Odin) drives one-click seed selection, rolling restarts, capacity changes,
  replacements, and decommissions — the framework encodes Cassandra-specific
  procedure knowledge.
- **Service-discovery-fed forked clients**: forked Go/Java drivers discover
  contact points dynamically and capture query fingerprints and feature-usage
  telemetry for production debugging and roadmap decisions.
- **Do the failure-rate arithmetic**: quantify operational toil (e.g., a 95%
  replacement success rate at 500 replacements/day means ~25 manual recoveries
  — roughly two dedicated engineers) to justify reliability investment and to
  recognize when automation must be paused.
- **Garbage state accumulates silently — purge it**: hint files for nodes no
  longer in the ring were never cleaned and were even handed down to
  successors on decommission, growing to terabytes; the fix was proactive
  orphan-hint purging plus dynamically raising the hint-transfer rate limit
  (whose default speed drops as clusters grow, stretching decommissions to
  days).
- **Expose internal state machines via metrics**: bootstrap and decommission
  had no externally probeable status, so the control plane could only block
  forever on intermittent failures; adding JMX-exposed state let automation
  observe and react, pushing replacement to 99.99% reliability.
- **Chase the minority-view node**: recurring LWT errors traced to one node
  believing in two pending token-range movements while the majority saw one;
  a purpose-built metric plus alert caught a gossip exception caused by DNS
  resolution of the replaced node's hostname failing long after the
  replacement finished, leaving that node's caches out of sync.
- **Harden the error path, not the happy path**: the durable LWT fix was
  better error handling inside the gossip protocol — an every-other-week
  incident class disappeared for over a year.
- **Make repair a built-in background process, like compaction**: instead of
  external orchestration tools, a repair scheduler inside Cassandra (its own
  thread pool, repair-history table in a replicated system keyspace,
  multi-node concurrency, sub-range splitting, retries) runs continuously
  with no manual intervention, cutting p99 repair duration from tens of days
  to single digits.

## When to apply / trade-offs

- The "self-orchestrating maintenance" idea generalizes: any recurring
  cluster chore that depends on an external cron/orchestrator (repairs,
  compactions, snapshot pruning) is a candidate for moving inside the system
  so it cannot be forgotten or misconfigured per cluster.
- Exposing lifecycle state via metrics is cheap and pays for itself the first
  time automation would otherwise hang on an opaque operation — a pattern
  worth applying to any long-running stateful transition (migrations,
  rebalances, backfills).
- Forking clients and the database buys deep integration and fast fixes but
  carries a permanent maintenance tax; Uber offsets it by upstreaming patches.
- The toil-arithmetic framing is a useful lens for prioritization debates:
  convert failure percentages into headcount before deciding whether an
  automation bug is "rare enough."
- Root-causing distributed flakiness (the LWT case) required adding
  observability first and only then catching the trigger in the act — an
  argument for instrument-then-wait over speculative fixes.

## Fidelity check

1. Claim: orphaned hint files grew into terabytes and slowed decommissions.
   Support: the capture states hints for departed peers were never purged,
   were transferred to successor nodes on decommission, and that the
   transfer rate limiter slows as node count grows, making large backlogs
   take days.
2. Claim: replacement automation became reliable after exposing
   bootstrap/decommission state over JMX. Support: the capture says the
   control plane previously had no way to probe decommission status and
   blocked forever on intermittent errors; after the JMX additions and other
   fixes, replacement reached 99.99% reliability, fully automated.
3. Claim: the LWT flakiness came from gossip failing on DNS lookups of the
   replaced node. Support: the capture describes the replacement flag
   carrying the leaving node's hostname, the new node's gossip path
   continuing to resolve that hostname after joining, and the eventual DNS
   failure desynchronizing its caches until a restart — fixed by improving
   gossip error handling, after which the issue vanished for about a year.
