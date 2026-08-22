---
source: https://innovation.ebayinc.com/stories/ebays-global-secondary-indexes/
author: eBay
license-note: ideas absorbed in own words; no text or code reproduced
---

# Global secondary indexes as their own sharded, replicated service

## What it teaches
Why eBay's in-house NuData document platform moved beyond per-shard local secondary
indexes (LSI) to a Global Secondary Index (GSI) tier that lives on its own shard fleet.
With data sharded by document-ID hash, any query on a non-key field (e.g. "this seller's
listing drafts priced $6-$10") must scatter to every data shard under LSI, then gather
and post-process (sorting, merging) centrally — making latency SLAs hard to guarantee.
A GSI is a separately stored, differently-sharded index whose entries are sorted by the
query's access pattern, so one lookup hits one index shard and covers the whole dataset.
The article also covers the operational skeleton: Raft-based replication (NuRaft) across
geographic zones, a purpose-fit storage engine (Jungle) serving both key lookups and
sequence-number scans for log replication, and a self-serve schema tool so customers
design their own indexes with platform guidance.

## Key patterns & decisions
- **Index tier separated from data tier**: GSIs get their own multi-shard fleet because
  real workloads need several indexes per dataset and index storage can exceed the base
  data's — co-locating them with data shards doesn't scale.
- **LSI scatter-gather as the anti-pattern being escaped**: per-shard indexes speed up
  each shard but still force fan-out to all shards plus central merge/sort, which defeats
  predictable-latency SLAs.
- **Shard base data by document ID, not user ID**: bulk-updating "power sellers" would
  hotspot a user-keyed shard; hashing on listing ID spreads their writes, and the GSI
  restores efficient per-user queries that this sharding choice gave up.
- **High-cardinality sharding key for the index itself**: a GSI only pays off if all
  entries for one sharding-key value fit in a single index shard; low-cardinality keys
  spill one key's entries across shards and reintroduce fan-out.
- **Covering indexes eliminate the second hop**: if the queried fields are all in the GSI
  entry, the answer comes straight from the index; otherwise a targeted primary-key fetch
  hits exactly one data shard — still no scatter.
- **Consensus replication for the index shards**: leader-based Raft (via eBay's NuRaft)
  handles election, membership, and log replication across local and remote zones;
  followers can absorb reads.
- **Storage engine chosen for dual access paths**: the engine (Jungle) must serve both
  by-key search for index reads and by-sequence-number search to feed Raft log
  replication and snapshots.
- **Self-serve schema-definition workflow**: customers know their documents and query
  shapes, the platform team knows storage behavior; a schema tool encodes that
  collaboration so customers register and deploy their own GSIs.
- **Eventual consistency as the launch trade-off**: index updates are asynchronous
  (extractor forwards new documents' index entries to the right GSI shard after the data
  write); synchronous and uniqueness-enforcing GSIs were deferred to a later release.

## When to apply / trade-offs
- Use a GSI-style tier when secondary-access-pattern queries against a hash-sharded store
  must meet latency SLAs; accept the extra storage, an asynchronous update path, and a
  window of index staleness.
- Every distinct query shape may need its own GSI, since sort-key structure — not merely
  which fields are included — determines which queries an index can serve. Budget storage
  accordingly.
- Index sharding-key design is the make-or-break decision; it requires knowledge of both
  data distribution and query mix, which argues for a structured schema-review process
  rather than ad-hoc index creation.
- Capacity elasticity matters: the system initially only grew by splitting a shard in
  two, with finer-grained scale-up/down still in development — plan for requirement drift.

## Fidelity check
1. Claim: base data is sharded on listing-ID hash specifically to avoid power-seller
   hotspots. Support: the capture explains that some sellers update many listings in one
   request, which would overwhelm a user-ID-keyed shard, so documents are placed by the
   listing ID's hash instead.
2. Claim: a GSI can fully answer a query or fall back to a single-shard primary-key
   fetch. Support: the capture's example says a quantity query on (user, price) is served
   directly from the GSI, while queries needing other fields fetch the original document
   by primary key from one specific shard rather than visiting all data shards.
3. Claim: the GSI was eventually consistent at publication with synchronous/unique
   variants planned. Support: the capture's roadmap section states the described GSI
   updates in an eventually consistent manner and that a synchronous and unique GSI
   feature was under development for early 2022.
