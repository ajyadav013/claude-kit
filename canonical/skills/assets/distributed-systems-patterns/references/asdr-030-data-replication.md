---
source: https://redis.com/blog/what-is-data-replication/
author: Redis (Paula Dallabetta)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Replication Taxonomy: Timing, Scope, and Conflict Strategy

## What it teaches

Replication is the continuous synchronization of data copies across nodes so
a system keeps serving *during* a failure, which the article carefully
distinguishes from backups — point-in-time snapshots you restore from *after*
one. The mechanics follow a three-stage lifecycle: seed each replica with a
baseline snapshot, capture ongoing changes (most cleanly by tailing the
transaction log — change data capture — which preserves commit order without
touching the source schema), and apply those changes on a cadence set by the
sync/async decision. A resilience detail worth keeping: when a replica
disconnects, it should first attempt a partial catch-up by replaying only the
missed entries from the primary's replication backlog, falling back to a full
re-snapshot only when the backlog has already rotated past what it missed.

The article frames replication's value through recovery math (RPO = tolerable
data loss window, RTO = tolerable downtime) and read scaling (replicas absorb
reads, often placed near users, freeing the primary for writes), then walks a
taxonomy of replication styles and their conflict-handling consequences.

## Key patterns & decisions

- **Replication vs backup as complementary layers**: replication covers
  availability mid-incident, backups cover restoration from corruption or
  deletion; production systems need both.
- **Log-based CDC as the capture mechanism of choice**: reading the
  transaction log detects inserts/updates/deletes with low source impact,
  keeps ordering, and ships only changed rows (bandwidth win) at the cost of
  setup and monitoring complexity.
- **Partial vs full resynchronization**: replay missed commands from a bounded
  replication backlog when possible; fall back to a fresh full snapshot when
  the gap exceeds the backlog.
- **Sync/async split along the latency boundary**: synchronous (primary waits
  for replica acknowledgment) buys alignment at a per-write round-trip cost
  and suits same-region links; asynchronous acknowledges immediately and
  accepts a lag window in which a primary crash loses unshipped writes. A
  common hybrid runs sync within a region and async across regions.
- **Style taxonomy mapped to use case**: ordered incremental streaming
  (snapshot + change stream) when every change must propagate; snapshot-only
  for seeding replicas or slowly-changing data; merge replication with
  explicit conflict rules for intermittently-connected nodes that write
  independently; key/watermark-based incremental sync (timestamp or
  monotonic ID) as a cheap pull mechanism whose blind spot is deletions — the
  removed row no longer exists to be detected.
- **Full vs partial replica scope**: full mirrors cost bandwidth and storage
  everywhere; partial replicas (region- or workload-relevant subsets) shrink
  both at the price of routing logic for non-local data.
- **Replication-lag countermeasures**: read-your-own-writes routing,
  synchronous replication on critical paths only, or application-level
  eventual-consistency handling — all decisions to make up front.
- **Multi-writer conflict resolution spectrum**: last-write-wins, custom
  application rules, or CRDTs that merge concurrent updates without dropping
  either; active-active multi-region designs lean on CRDTs so every node
  serves local reads and writes with no failover pause, but data-type choice
  matters because some types still degrade to last-write-wins.

## When to apply / trade-offs

Choose the replication mix from four inputs: latency tolerance, RPO/RTO
targets, geographic spread, and write volume — most real systems combine
several styles rather than standardizing on one. Costs to budget for:
per-replica infrastructure, stale reads under lag, conflict-resolution design
whenever more than one node accepts writes, and cross-region bandwidth.
Active-active removes failover delay and cross-region write latency but adds
architectural complexity and constrains data-type selection.

## Fidelity check

1. *Claim: key/watermark-based incremental replication cannot see deletes.*
   The capture states this method finds changed records via a timestamp or
   incrementing ID column, and its main limitation is that deletions remove
   the very row the replication key would have flagged.
2. *Claim: reconnecting replicas replay a backlog before resorting to a full
   snapshot.* The capture describes partial resynchronization replaying only
   missed commands from the replication log, with a full snapshot transfer
   only when those commands have aged out of the primary's backlog.
3. *Claim: active-active conflict handling is CRDT-first with a
   last-write-wins fallback.* The capture says the active-active geo model
   resolves most write conflicts automatically via CRDTs but falls back to
   last-write-wins for certain data types (strings named specifically), so
   type selection matters for concurrent cross-region writes.

## Notes

Vendor-authored (Redis) — the taxonomy and trade-offs are generic and sound,
but the active-active section doubles as product marketing for Redis
Cloud/Software.
