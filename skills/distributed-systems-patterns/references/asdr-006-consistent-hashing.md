---
source: https://algomaster.io/learn/system-design/consistent-hashing
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Consistent hashing: stable key ownership under changing cluster membership

## What it teaches
When a distributed system must decide which node owns a key (cache entry,
shard, worker assignment), the naive approach of hashing the key modulo the
live node count breaks catastrophically on membership change: growing or
shrinking the fleet by one node reassigns most keys, causing cache-miss
storms, mass data migration, and lost locality. Consistent hashing fixes
this by placing both nodes and keys on a shared fixed hash space (a ring),
so a membership change only relocates the keys adjacent to the changed node
— roughly 1/(N+1) of the keyspace when adding to N balanced nodes. The
chapter also stresses what the technique is *not*: it is placement logic
only, not replication, migration, or durability.

## Key patterns & decisions
- **Ring placement over modulo-by-node-count** — hash keys and nodes into
  one fixed space; a key belongs to the first node clockwise from its
  position, so node churn moves only a local range of keys instead of
  reshuffling everything.
- **Virtual nodes (vnodes) for balance and blast-radius control** — placing
  each physical node at many ring positions evens out range sizes, spreads
  a failed node's load across several successors instead of one, and lets
  bigger machines take proportionally more vnodes (weighted capacity).
- **Stable node identity as an operational requirement** — keying the ring
  on something ephemeral like an IP makes a rescheduled instance look like
  a new node and triggers pointless key movement; use durable names or a
  persisted UUID.
- **Separate routing changes from data rebalancing** — updating the ring
  changes where keys *should* live; a storage system still needs throttled
  background migration, repair, and progress tracking, while a cache can
  merely eat cold misses.
- **Membership view consistency** — clients with divergent ring snapshots
  route the same key to different owners; solve with a config service,
  versioned gossip, or a control plane publishing ring versions.
- **Hot-key mitigation is out of scope for the ring** — consistent hashing
  balances ownership, not request volume; extremely popular keys need
  coalescing, local caching, hot-key replication, or tenant splitting.
- **Replica selection by clockwise walk with placement constraints** —
  successive distinct physical nodes serve as replicas, subject to rules
  like never co-locating replicas on one node/rack/zone.
- **Know the alternatives** — rendezvous hashing (small/medium node sets,
  no ring), jump consistent hash (numbered, mostly append-only buckets),
  and fixed logical partitions moved by a control plane (the pattern many
  modern databases and log systems prefer, since it decouples key hashing
  from physical membership entirely).

## When to apply / trade-offs
- Reach for consistent hashing when keys need sticky owners and nodes come
  and go: distributed caches, Dynamo-style stores, stateful routing, keyed
  stream worker assignment, tenant-to-shard mapping.
- Skip it for stateless traffic where any node can serve any request —
  plain load balancing is simpler and more flexible there.
- Modulo hashing remains fine when the divisor is a *fixed* partition
  count (Kafka-style), because partitions, not nodes, absorb the churn.
- Vnode count is a tuning knob: too few gives lumpy load, too many inflates
  memory and membership-update cost; cache clients commonly start in the
  tens-to-hundreds per physical node.
- Prefer a fast non-cryptographic hash with good distribution in
  production; a cryptographic hash works but is slower than needed.

## Fidelity check
1. Claim: adding one node to a balanced N-node ring moves about 1/(N+1) of
   keys. Capture support: the chapter states this fraction explicitly when
   describing how a newly inserted node claims only the range between its
   predecessor and itself.
2. Claim: vnodes soften failure impact. Capture support: with one point per
   physical node, a failure dumps the entire owned range onto a single
   successor; with many vnodes the failed node's ranges scatter across
   several successors, and vnodes also enable weighting larger machines.
3. Claim: consistent hashing is placement only. Capture support: the text
   explicitly warns that replication, quorum reads, conflict resolution,
   durability, and actual data movement are separate design concerns the
   ring does not provide.
