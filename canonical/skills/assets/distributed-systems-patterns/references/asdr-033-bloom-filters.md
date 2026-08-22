---
source: https://algomaster.io/learn/system-design/bloom-filters
author: algomaster.io (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Bloom filters: cheap "definitely not here" checks in front of expensive lookups

## What it teaches

A Bloom filter is a compact probabilistic set-membership structure whose whole value
comes from an asymmetric guarantee: a negative answer is certain, a positive answer is
only probable. It never stores the items themselves — just a bit array of length m
plus k hash functions. Inserting an item sets the k hashed bit positions to 1;
querying re-hashes and inspects those positions. Any single 0 bit proves the item was
never inserted; all-1s means "maybe — some combination of other items could have set
these same bits."

The engineering payoff is skipping work. Systems spend enormous effort searching for
things that do not exist (missing cache keys, keys absent from a storage file, URLs a
crawler has never seen), and a tiny in-memory filter can veto most of those wasted
lookups before they touch disk or the network.

The article also covers correct sizing: you must commit up front to an expected item
count n and a tolerable false-positive rate p, and derive m and k from them. Rough
budget: ~10 bits per item and ~7 hash functions buys a 1% false-positive rate;
tightening to 0.01% costs roughly double the bits. Overfilling past the planned
capacity saturates the bit array and the false-positive rate climbs fast. Hashing
must be deterministic across processes and well-spread; language-default hashes that
are seeded per-process (e.g., Python's builtin) will corrupt a filter that is
persisted or shared. Real implementations commonly derive all k positions from two
base hashes (double hashing) rather than running k independent hash functions.

## Key patterns & decisions

- **Negative-lookup short-circuit**: place a Bloom filter before any expensive
  membership check so a certain "no" skips the disk read / cache call / RPC entirely.
- **One-sided error contract**: no false negatives for properly inserted items, only
  false positives — so a "yes" must always be treated as "go verify at the source."
- **False positives may only cost extra work, never wrong behavior**: safe for "check
  this SSTable / cache / URL anyway"; unsafe for authorization, payment-dedup, or
  legal-consent decisions where a wrong "yes" changes the outcome.
- **Capacity-first sizing**: pick n and p before deployment, derive m and k; treat
  bits-per-item (~5 for 10%, ~10 for 1%, ~19 for 0.01%) as the memory budget.
- **Double hashing for k positions**: generate all probe positions from two stable
  base hashes instead of k separate hash functions.
- **Stable, well-distributed hashes only**: never a per-process-randomized default
  hash when the filter outlives a process or crosses service boundaries.
- **Variant selection by requirement**: counting Bloom filter when deletion of
  known-inserted items is needed (more memory, corruptible by deleting never-added
  items); scalable Bloom filter when capacity is unknown (multi-filter lookups,
  compounded error rate); cuckoo filter when deletion is frequent (fingerprints in
  buckets); ribbon filter for static build-once/query-many sets.
- **Sketch-family selection**: Bloom for membership, HyperLogLog for distinct counts,
  Count-Min Sketch for frequencies — choose by the question, not the buzzword.

## When to apply / trade-offs

Apply when misses dominate and a wasted lookup is expensive: LSM-tree engines
(Cassandra, RocksDB) attach a filter per SSTable so point reads skip immutable files
that cannot hold the key; caches use a filter as a negative pre-check; crawlers dedup
URLs at billion scale where an exact set would blow memory. Cassandra even exposes
the per-table false-positive target as a tunable — lower p costs more RAM and may
need compaction to apply to old files.

Avoid when you need exactness (compliance/archival crawling needs a real visited
set), enumeration of members, value retrieval, or safe deletion in the standard form.
The filter is not free memory-wise (hundreds of MB for 10^8 keys at 1%), is not
adversary-resistant by default (crafted inputs can inflate false positives), and a
misconfigured one silently degrades rather than erroring.

## Fidelity check

1. Claim: a single 0 bit at any probed position proves absence. Capture support: the
   worked URL-dedup example shows a query for a never-inserted domain finding one
   unset bit among its hash positions and concluding "definitely absent," with the
   explanation that insertion would have set all of that item's positions.
2. Claim: ~1% false positives costs roughly 9.6 bits/item and ~7 hash functions.
   Capture support: the sizing table lists bits-per-item and hash-count pairs for
   target rates 10%, 1%, 0.1%, and 0.01% (~4.8/3, ~9.6/7, ~14.4/10, ~19.2/13).
3. Claim: LSM engines use per-SSTable filters to skip files during point lookups, and
   Cassandra makes the false-positive chance tunable per table. Capture support: the
   production-uses section describes Cassandra/RocksDB skipping immutable sorted
   files that definitely lack the key, and notes Cassandra's per-table tuning where
   lower rates use more memory and existing SSTables may need rewriting/compaction.
