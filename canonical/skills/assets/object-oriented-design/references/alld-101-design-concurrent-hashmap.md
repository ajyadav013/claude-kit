---
source: https://algomaster.io/learn/concurrency-interview/design-concurrent-hashmap
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Evolving a hash map from one big lock to striped locks to CAS

## What it teaches
How to make a chained hash table safe under many readers and writers without
turning it into a serial bottleneck. The chapter is structured as a
progression of three designs, each fixing the scaling limit of the previous
one, and it grounds the designs in four concrete failure modes of a naive map:
two inserts into the same bucket both reading the old chain head, so one node
is silently orphaned (a lost update); any put being a read-modify-write triple
that another thread can interleave into, producing duplicates or a corrupted
chain; a resize migrating entries while a reader still walks the old table,
so an existing key answers null; and compound operations like insert-if-absent
where two threads both see "absent" and both believe their insert won.

Design one is a single lock around everything. It is trivially correct,
cannot deadlock, and makes compound operations atomic for free, but it
serializes even reads of unrelated keys, so throughput never scales with
cores. Design two is lock striping: partition buckets into a fixed number of
segments (sixteen is the classic default), give each segment its own lock,
and route each key to its segment by hash. Operations on different segments
run fully in parallel; only same-segment operations queue. The costs surface
in whole-map operations — an exact size() must take every segment lock in a
fixed global order (that ordering is also the deadlock defense), and
iteration degrades to "weakly consistent": it may or may not reflect
concurrent edits, yields each element at most once, and never throws a
modification error.

Design three, modeled on the modern JDK rewrite, drops segments. Reads take
no lock at all, relying on a volatile table reference, volatile node values,
and nodes whose key/hash are frozen after publication. A write into an empty
bucket installs the first node with a single compare-and-swap; only when a
bucket already has occupants does the writer lock that one bucket head, which
also gives compound check-then-insert its atomicity. Resizing is incremental:
a bigger table is allocated, migrated buckets are stamped with forwarding
markers, threads that stumble on a marker either help migrate or follow it to
the new table — no stop-the-world pause.

## Key patterns & decisions
- Lock striping: N segment locks bound worst-case contention to 1/N of traffic while keeping per-key operations simple; the interview-default answer.
- Fixed global lock-acquisition order for multi-segment operations (exact size, clear) as the standard deadlock preventer.
- Weakly consistent iteration as a deliberate contract: approximate views are fine for logging/monitoring, and demanding a snapshot would mean locking the world.
- CAS-install for the empty-bucket fast path, falling back to a per-bucket-head lock only on collision — optimize for the common case that buckets hold zero or one entry.
- Lock-free reads via safe publication: volatile table/value references plus immutable-after-publish nodes mean a reader can never observe a half-built entry.
- Incremental resize with forwarding markers so migration cost is spread across threads and readers are redirected instead of blocked.
- Compound operations (put-if-absent, compute-if-absent) must be atomic at the map level; callers cannot bolt atomicity on from outside.

## When to apply / trade-offs
Use the coarse lock for prototypes, low contention, and as the oracle in
stress tests of fancier versions. Striping is the sweet spot of complexity
versus scaling and the recommended interview starting point; describe the
CAS-based design as the optimization. In production, never hand-roll: reach
for the platform's battle-tested concurrent map (JDK, TBB/folly for C++,
process-based sharing in Python where threads don't help). The recurring
trade: every step up in parallelism is paid for in reasoning difficulty —
CAS loops, memory-ordering rules, and forwarding-node protocols are a
different maintenance class from a lock.

## Fidelity check
- Claim: the canonical lost-update bug is two same-bucket inserts both reading the old chain head. Support: the capture's first challenge walks threads inserting A and B where B's write overwrites the bucket head that pointed at A, leaving A unreachable.
- Claim: exact size under striping requires locking all segments in a fixed order. Support: the capture calls size() out as the cross-segment problem case, notes counting without all locks is inconsistent, and lists fixed-order acquisition as why the design stays deadlock-free.
- Claim: the CAS-era design locks only on bucket collision and never for reads. Support: the capture's key-insight section says empty buckets get a CAS-installed first node, non-empty buckets synchronize on the head node, and gets rely purely on volatile reads over immutable-once-published nodes.
