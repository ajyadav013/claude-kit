---
source: https://algomaster.io/learn/concurrency-interview/coarse-vs-fine-grained-locking
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Lock granularity: how much data one lock should guard

## What it teaches

Lock granularity is the dial between one lock over an entire structure
(coarse-grained) and a lock per element (fine-grained), with lock striping as the
pragmatic midpoint. The core failure mode motivating the topic is contention: a
single lock over a shared hash table serializes every operation, so a many-core
machine degrades to effectively single-core behavior even when concurrent threads
touch completely unrelated keys. Conversely, going maximally fine costs memory,
implementation complexity, and deadlock exposure. There is no universally correct
setting — the right granularity is a function of contention level, workload shape,
and how often you need whole-structure operations.

The three concrete designs discussed: a coarse list where every method takes the
same lock (simple, deadlock-free by construction, but even pure reads exclude each
other); a striped hash map where a fixed number of locks each guard a hash-derived
slice of buckets (the pre-Java-8 ConcurrentHashMap approach — hash the key, modulo
by stripe count, lock only that stripe); and hand-over-hand (lock-coupling)
traversal of a linked list, where a thread holds the predecessor's lock while
taking the current node's lock so no one can mutate the link being crossed, and a
sentinel head node removes the first-element special case.

The scalability numbers make the argument concrete: under a read-heavy benchmark,
the coarse version is actually slightly faster single-threaded (no striping
overhead), but throughput inverts hard as threads are added — coarse throughput
falls as queueing grows while striped throughput climbs, reaching an order-of-
magnitude-plus gap at 16 threads.

## Key patterns & decisions

- Lock striping for hash structures: a fixed pool of N locks indexed by
  hash-modulo bounds memory and complexity while letting operations on different
  stripes run fully in parallel; collision probability on a stripe is 1/N.
- Hand-over-hand (lock coupling) for linked traversal: hold the predecessor lock
  while acquiring the successor's, releasing behind you as you advance — enables
  safe concurrent traversal and unlinking of different list regions.
- Sentinel node to eliminate edge cases: a permanent dummy head guarantees every
  real node has a lockable predecessor, removing remove-first special-casing.
- Ordered all-lock acquisition for global operations: an exact size or consistent
  snapshot over a striped structure requires taking every stripe lock in a fixed
  order (deadlock avoidance) and releasing in reverse — deliberately expensive.
- Weak consistency as a design escape hatch: production concurrent collections
  often ship approximate sizes and weakly consistent iterators because paying for
  strong global consistency negates the parallelism the striping bought.
- Coarse-by-default under low contention: when threads rarely collide, the single
  lock's simplicity and zero deadlock risk beat theoretical parallelism gains.
- Measure before refining: decide granularity from measured throughput, tail
  latency (P99+), thread-scaling curves, and per-element lock memory, not
  intuition — the coarse/striped crossover point is workload-dependent.
- Deadlock risk scales with granularity: one lock cannot circular-wait; multiple
  locks demand a global ordering discipline the moment any operation spans two.

## When to apply / trade-offs

Walk the decision tree: low contention → stay coarse; frequent global operations
(size, iteration, snapshots) → coarse or copy-on-write/immutable-snapshot designs,
because fine granularity makes global views expensive; bounded hash-addressable
structure under high contention → striping (the proven production pattern);
traversal-dominated linked structures needing maximal concurrency → per-node
locking, if you can afford the complexity and testing burden. The recurring trap
is refining granularity reflexively: finer locking adds per-element memory,
multi-acquire cost per operation, and deadlock surface, and only pays off when
contention is actually the measured bottleneck.

## Fidelity check

1. Claim: striping bounds lock count regardless of element count while retaining
   most parallelism. Support: the capture describes distributing many buckets
   across a small fixed set of stripe locks via hash-then-modulo, with typical
   stripe counts like 16 or 32 and only a 1/N chance two random keys share a
   stripe.
2. Claim: coarse locking can beat striping at one thread but loses badly as
   concurrency rises. Support: the capture's benchmark table shows the coarse map
   ahead at a single thread (striping overhead with zero contention) and the
   striped map roughly an order of magnitude or more ahead by 8–16 threads.
3. Claim: exact global operations on a striped map require acquiring all stripe
   locks in a fixed order. Support: the capture's size-operation discussion
   explains taking all locks in ascending order to prevent deadlock, counting,
   then releasing in reverse — and notes real systems often prefer approximate
   answers to avoid this cost.
