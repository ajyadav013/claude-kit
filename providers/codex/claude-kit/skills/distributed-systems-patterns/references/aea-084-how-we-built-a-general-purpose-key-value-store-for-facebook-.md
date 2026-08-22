---
source: https://engineering.fb.com/2021/08/06/core-infra/zippydb/
author: Meta Engineering (Sarang Masti)
license-note: ideas absorbed in own words; no text or code reproduced
---

# ZippyDB: one managed key-value platform with per-request consistency dials

## What it teaches

Before ZippyDB, teams across Facebook each wrapped RocksDB themselves and each
re-solved replication, failover, and capacity management. ZippyDB's founding move
was consolidation through composition: build one reusable replication library (Data
Shuttle) and layer it over already-proven infrastructure — RocksDB as the storage
engine, an external shard manager for placement and failover, and a
ZooKeeper-backed configuration service. The result is a single multitenant
key-value platform whose main selling point is not raw speed but *tunable*
durability, consistency, and latency, chosen per use case and even per request.

The architecture teaches a series of layered indirections: deployments are grouped
into multitenant tiers (a default shared tier, with dedicated tiers only for strict
isolation needs); data splits into server-side physical shards; and applications
see only micro-shards (μshards), thousands of which pack into each physical shard,
so the platform can reshard invisibly. Replication mixes a Multi-Paxos quorum
("global scope") with optional async follower replicas, letting a use case buy
low-latency in-region reads without inflating the write quorum.

## Key patterns & decisions

- **Reuse-first platform assembly**: build the one genuinely new piece (a
  replication library) and compose everything else from existing storage, shard
  management, and configuration services rather than writing a database from
  scratch.
- **Multitenant-by-default tiering**: a shared "wildcard" tier maximizes hardware
  utilization and minimizes ops burden; dedicated tiers are the exception, granted
  for isolation requirements.
- **Two-level sharding (μshards over physical shards)**: applications key their
  data into micro-shards; the platform maps tens of thousands of them onto each
  50–100 GB physical shard, enabling transparent resharding with zero client
  change. Mapping is either mostly-static (compact) or dynamically placed near
  access locality by a placement service (Akkio), which cuts duplication versus
  replicating everywhere.
- **Mixed sync/async replica roles per shard**: a small Paxos quorum gives
  durability; extra async followers give cheap, slightly-stale in-region reads —
  each use case tunes the durability/latency/read-performance triangle by
  configuring replica roles and region-placement hints.
- **Epoch-based leadership with leases from an external arbiter**: time is carved
  into epochs, each with one leader assigned by the shard manager and kept alive by
  heartbeat leases; the leader totally orders writes with monotonically increasing
  sequence numbers into a Paxos-replicated log. (Acknowledged trade-off: external
  failure detection is simpler but slower; they planned to move detection in-band.)
- **Per-request consistency levels**: default writes persist to a majority's logs
  plus the primary's storage engine before ack; a fast-ack mode acknowledges on
  enqueue at the primary for latency-sensitive writers willing to weaken
  guarantees. Reads pick eventual (actually bounded staleness — laggy replicas are
  fenced out via heartbeat-measured lag), read-your-writes (client caches the last
  write's sequence number and issues at-or-later reads), or linearizable.
- **Lease-owning primary serves strong reads without a quorum round trip**,
  degrading to a quorum check only when lease renewal is in doubt.
- **Serializable-only OCC transactions scoped to an epoch**: clients read a
  snapshot (often from a secondary), submit read+write sets; the primary admits the
  transaction only if no admitted concurrent writer conflicts. Recent-write history
  is bounded, so a minimum tracked version rejects transactions reading below it,
  and cross-epoch transactions are simply rejected to keep tracking local.
- **Conditional writes as server-side transactions**: common preconditions (key
  present/absent, value matches) are converted into the transaction machinery
  server-side, avoiding a client read round trip.
- **Native TTL by piggybacking on the storage engine's compaction**: expired keys
  are filtered at read time and physically reclaimed during periodic compaction.

## When to apply / trade-offs

This is the playbook for turning N teams' copies of "a storage engine plus homegrown
replication" into one platform: invest in the replication/consistency layer, reuse
everything else, and expose the trade-off dials instead of picking one point on the
curve. Key trade-offs to copy consciously: fast-ack writes trade durability for
latency; async followers trade freshness for read locality; serializable-only
transactions trade flexibility for simple correctness reasoning; epoch-scoped
conflict tracking trades cross-epoch transaction support for a small, purgeable
write history; external failure detection trades failover speed for initial
simplicity.

## Fidelity check

1. Claim: applications never see physical shards. Capture support: the post
   describes physical shards of roughly 50–100 GB each hosting tens of thousands of
   μshards, with the μshard layer existing precisely so data can be resharded
   without client-side changes.
2. Claim: ZippyDB's "eventual" reads are really bounded staleness. Capture support:
   the article says writes are totally ordered per shard and replicas lagging
   beyond a configurable threshold (detected via heartbeats) are excluded from
   serving, making the mode closer to bounded staleness than textbook eventual
   consistency.
3. Claim: transactions crossing epoch boundaries are rejected by design. Capture
   support: conflict detection relies on the primary tracking recent writes from
   transactions admitted in the same epoch, so cross-epoch transactions are refused
   to avoid replicating that tracking state, and a minimum tracked version guards
   serializability once old history is purged.
