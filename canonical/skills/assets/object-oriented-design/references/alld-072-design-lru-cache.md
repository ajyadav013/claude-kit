---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/lru-cache.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Constant-time LRU cache from two cooperating structures

## What it teaches

The classic lesson that no single data structure gives you an LRU cache, but
a pair of them does: a hash map for O(1) key lookup and a doubly linked list
for O(1) recency reordering and eviction. Each structure covers the other's
weakness — the map cannot express order, the list cannot do random access —
and the design's whole job is keeping the two views consistent under every
operation, including concurrent ones.

## Key patterns & decisions

- **Hash map + doubly linked list pairing.** Map entries point at list
  nodes; the list is ordered by recency with most-recent at the head and the
  eviction candidate at the tail. Both reads and writes stay O(1).
- **Node as the unit of truth.** Each list node carries the key as well as
  the value, so that when the tail is evicted the corresponding map entry
  can be removed without a reverse lookup.
- **Read operations mutate order.** A cache hit is not read-only: a
  successful lookup splices the node out of its current position and
  re-inserts it at the head, encoding "recently used" directly in structure
  rather than in timestamps.
- **Eviction folded into insertion.** Adding a new key when the cache is
  full first drops the tail node (least recently used), then inserts at the
  head; updating an existing key rewrites the value and promotes the node.
  Capacity is fixed at construction time.
- **Small private list-surgery helpers.** The pointer manipulation is
  isolated in a handful of internal operations (attach at head, detach a
  node, promote a node, drop the tail) so the public API reads as policy
  and the helpers hold all the fiddly pointer code.
- **Coarse-grained thread safety.** Both public operations are serialized
  with a single mutual-exclusion boundary (method-level synchronization),
  which is correct precisely because even a read reorders the list.
- **Sentinel-friendly structure.** The head/tail bookkeeping style used
  here is commonly implemented with dummy boundary nodes to remove
  null-checking edge cases — the design invites that refinement.

## When to apply / trade-offs

- Reach for this design whenever you need bounded memory with
  recency-based eviction: session caches, connection metadata, memoization
  with a cap. It is also the canonical warm-up for LFU and TTL variants.
- Method-level locking is simple and safe but makes the cache a serial
  bottleneck under contention; production-grade alternatives use striped
  locks, lock-free queues of recency events, or accept approximate LRU
  (as Redis does) to regain concurrency.
- Because hits mutate shared state, a "read-mostly" workload does not help
  you here — every access is a write to the list. That is the key
  difference from a plain concurrent map and the reason naive
  reader-writer locks do not apply cleanly.
- If exact recency is not required, cheaper policies (clock/second-chance,
  random-sampled LRU) trade a little hit-rate for much less coordination.

## Fidelity check

1. *Claim:* the design combines a hash map with a doubly linked list to hit
   O(1) for both operations. *Support:* the capture describes the cache
   class as built from a map plus a head/tail doubly linked list, with an
   explicit requirement of ideally constant-time get and put.
2. *Claim:* a cache hit promotes the entry to most-recently-used position.
   *Support:* the capture states that a successful lookup moves the node to
   the head of the list before returning its value.
3. *Claim:* thread safety is achieved by serializing the public methods.
   *Support:* the capture notes that the two public operations carry
   method-level synchronization to allow safe concurrent access.
