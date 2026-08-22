---
source: https://algomaster.io/learn/concurrency-interview/design-concurrent-bloom-filter
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Lock-free Bloom filters: when idempotent monotonic writes make CAS trivial

## What it teaches
Why a Bloom filter is unusually easy to parallelize, and how to exploit that.
The structure is an m-bit array plus k hash functions; adding sets k bits,
querying answers "definitely absent" if any bit is zero and "maybe present"
if all are one. The rule of thumb given: about ten bits per expected element
yields roughly a one-percent false-positive rate. High-traffic systems
(database engines skipping disk probes, caches prefetching, routers
deduplicating packets) run these at millions of ops per second, so lock
contention is intolerable.

Two structural properties do the heavy lifting. First, writes are monotonic:
a bit only ever goes 0→1 during normal operation, never back, which is why
the ABA hazard that plagues compare-and-swap designs simply cannot occur.
Second, writes are idempotent: two threads setting the same bit produce the
same result as one, so there is no such thing as a lost update. Together
these mean the k bit-sets of a single add do not need to be atomic as a
group — a query that overlaps an in-flight add and answers "absent" is a
legal linearization (the query ordered before the add), and the sacred
invariant, no false negatives for completed adds, survives untouched.
Relaxed consistency is thus a feature: eventual visibility of freshly set
bits is acceptable, and full linearizability is explicitly not required.

Three designs are compared. A read-write-locked wrapper is the trivially
correct baseline, made worse by the fact that a language's standard bitset is
often not thread-safe even for reads, forcing exclusive locking everywhere
and killing all parallelism. Segmented locking splits the bit array into
independently locked regions; an add touching several segments must take
their locks in ascending segment order to avoid deadlock, and scaling decays
as k spreads bits across more segments. The recommended design packs bits
into an array of atomic 64-bit words: setting a bit is a small CAS retry
loop OR-ing the target bit into its word, and querying is a plain atomic
read — wait-free, no loop at all. Memory-ordering is tiered to cost: acquire
on query reads, release on a successful bit-set CAS, and fully relaxed for
the approximate insert counter and for clear-time writes.

The one genuinely dangerous operation is clear(). Zeroing words while an add
is mid-flight can wipe some of an element's bits after the add reported
success — manufacturing a false negative, the one forbidden outcome. So
clear must be globally exclusive, typically via a read-write lock where adds
and queries share the read side and clear alone takes the write side.

## Key patterns & decisions
- Idempotent, monotonic bit-sets (1 OR 1 = 1, 0→1 only) as the structural properties that make lock-free operation safe and ABA-immune.
- Per-add atomicity deliberately dropped: an overlapping query linearizes before the incomplete add, preserving no-false-negatives without group atomicity.
- Bits packed into atomic 64-bit words with a CAS-OR retry loop for sets and bare atomic reads for wait-free queries.
- Tiered memory ordering — acquire/release only where visibility matters, relaxed for approximate counters — instead of blanket sequential consistency.
- clear() as the exclusive-mode exception, gated by a read-write lock so it cannot shear a concurrent add into a false negative.
- Segment locks with ascending-order acquisition as the deadlock-safe middle option when lock-free skills are unavailable.
- ~10 bits/element ≈ 1% false-positive sizing heuristic for capacity planning.

## When to apply / trade-offs
Default to the lock-free design for high-throughput paths: wait-free reads,
linear scaling with cores, and an implementation that is honestly simpler
than most lock-free structures because idempotence removes the usual hazards.
Fall back to the locked or segmented versions when throughput is modest
(under ~100K ops/sec), when clear() is frequent (it re-serializes the
lock-free design anyway), or when the team cannot maintain memory-ordering
code. The transferable meta-lesson: before reaching for locks, check whether
your writes are idempotent and monotonic — if so, most classical race
conditions are already impossible by construction.

## Fidelity check
- Claim: Bloom filters are immune to the ABA problem. Support: the capture states bits transition only from 0 to 1 during normal operation and never revert (outside exclusive clear), so a CAS can never be fooled by an A→B→A cycle.
- Claim: a query overlapping a partial add is correct, not a bug. Support: the capture's first challenge concludes the "not present" answer is a valid linearization placing the query before the insert's completion, keeping the no-false-negative guarantee for completed inserts.
- Claim: unsynchronized clear() can create false negatives. Support: the capture's clear() challenge describes an added element becoming unfindable because two of its bits were zeroed mid-insertion, and mandates exclusive access via the write side of a read-write lock.
