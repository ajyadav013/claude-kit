---
source: https://algomaster.io/learn/concurrency-interview/reader-writer-pattern
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Reader-writer locks: parallel reads, exclusive writes, and the starvation problem

## What it teaches

Why a plain mutex is wasteful for read-dominated shared state, and what it
costs to fix that. Reading does not mutate, so any number of readers can
overlap safely; only mutation needs exclusivity. A single mutex ignores this
and serializes a hundred harmless reads behind each other. The reader-writer
lock encodes the real invariant — many concurrent readers OR exactly one
writer, never a mix — and the chapter illustrates the payoff with a
back-of-envelope model: a hundred 1 ms reads plus one 10 ms write cost about
110 ms fully serialized, but roughly 11 ms when the reads parallelize and
only the write serializes, an order-of-magnitude win for read-heavy loads.

The deeper lesson is that the hard part is not the lock, it is fairness:
deciding who goes next when readers and writers are simultaneously waiting
determines whether one side starves.

## Key patterns & decisions

- **Shared/exclusive lock split**: a read (shared) mode countable to many
  holders, and a write (exclusive) mode that requires zero active readers
  and zero other writers. A write holder may also read; a read holder must
  not write.
- **Active-reader counter with a zero-crossing signal**: the lock tracks
  how many readers are inside; the transition to zero is the event that
  admits a pending writer, and notifying only on that last-reader exit is
  a wakeup-avoidance optimization.
- **Fairness policy is an explicit design axis with three options**:
  reader-preference (new readers overtake waiting writers — writers can
  starve under a steady read stream), writer-preference (a waiting writer
  blocks new readers — readers can starve under frequent writes), and
  FIFO/fair ordering (no starvation, but readers batch less so throughput
  drops).
- **Waiting-writer registration**: writer-priority schemes require writers
  to announce themselves while blocked, so the lock can hold new readers
  at the door; a pending-writes count checked on read-acquire implements
  this.
- **Broad notification on write release**: both reader and writer threads
  may be parked when a writer exits, so the release wakes all waiters and
  lets the policy sort out who proceeds.
- **MVCC as the more permissive cousin**: databases sidestep
  reader-vs-writer blocking entirely by letting readers consume snapshots
  while writers create new versions — the same intent (reads never
  conflict) achieved without blocking reads during writes.
- **Escalation ladder of alternatives**: plain mutex when read/write mix is
  balanced; copy-on-write when writes are vanishingly rare; an atomically
  swapped reference when the state is one pointer; snapshots/MVCC when
  reads must never block; lock-free CAS structures when throughput is
  paramount.

## When to apply / trade-offs

The pattern earns its overhead only when reads heavily outnumber writes
(the chapter suggests around 10:1 or more) and individual reads are short —
a long-held shared lock delays writers just as badly as a mutex would.
With a balanced mix, the bookkeeping (counter maintenance, policy checks)
makes it slower than a simple mutex. The chapter's worked scenario is a
configuration store: constant concurrent reads, rare atomic updates, no
stale reads mid-update — the archetypal fit. Choosing the fairness policy
is the real engineering decision, and it should be driven by which side's
latency matters more and which side's arrival pattern is steadier.

## Fidelity check

1. Claim: the throughput win over a mutex is roughly 10x in the chapter's
   model. Supported: the capture computes 100 one-millisecond reads plus a
   ten-millisecond write as about 110 ms under a mutex versus about 11 ms
   with parallel reads followed by the serialized write.
2. Claim: reader-preference risks writer starvation specifically under a
   continuous stream of readers. Supported: the capture describes new
   readers repeatedly slipping in ahead of a blocked writer because
   admission only checks for an *active* writer, leaving the writer waiting
   indefinitely.
3. Claim: fair FIFO ordering eliminates starvation at a throughput cost.
   Supported: the capture's policy table and discussion state that serving
   requests in arrival order prevents either side from starving but reduces
   throughput because readers arriving after a queued writer can no longer
   coalesce into one concurrent batch.
