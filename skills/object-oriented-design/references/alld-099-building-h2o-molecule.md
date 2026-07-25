---
source: https://algomaster.io/learn/concurrency-interview/building-h2o
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Ratio-constrained group formation: admission control plus a barrier

## What it teaches
Two populations of threads arrive in arbitrary order and must be released in
exact fixed-ratio groups — two of one kind, one of the other — with each group
fully assembled and passed through a common synchronization point before the
next group may start forming. The chapter's central idea is a two-layer
decomposition: an admission layer (counting semaphores sized to the ratio)
that limits how many of each kind may even attempt to join the current group,
and a coordination layer (a barrier sized to the group total) that ensures no
member proceeds until the whole group is present. A completion callback then
re-arms the admission layer for the next group. It also demonstrates how to
emulate the barrier with plain semaphores when the platform lacks one.

## Key patterns & decisions
- Layered admission + rendezvous: semaphores initialized to the per-kind quota
  (two and one) gate entry, so at most one group's worth of threads is ever
  "in flight"; a three-party barrier then makes the admitted trio cross
  together. Ratio correctness and simultaneity are enforced by different
  mechanisms, cleanly separated.
- Reset in the barrier's completion action: the permits for the next group are
  released only when the current group has fully crossed, which serializes
  group formation and prevents the next batch from mixing with the current one.
- Naive shared counters fail on non-atomic multi-party check-then-decrement:
  three woken threads can each see the "group ready" condition, decrement
  independently, and leave one member stranded when the condition flips false
  mid-sequence — or admit too many of the rarer kind into one group.
- Semaphore-only barrier emulation: a mutex-protected pair of arrival counters
  plus per-kind queue semaphores (initialized to zero); whichever thread's
  arrival completes the quota becomes the ad-hoc coordinator, decrements the
  counts, and releases exactly the group's worth of permits, consuming its own.
- Release the mutex before blocking: holding the count-protecting lock while
  waiting for groupmates would stop later arrivals from registering — the
  classic hold-and-wait deadlock — so the wait must happen outside the lock.
- Excess arrivals self-queue at the admission semaphore: a third same-kind
  thread simply blocks until the callback re-issues permits, giving natural
  backpressure and per-group fairness without extra logic.
- Starvation freedom is delegated to primitive fairness: both designs are
  only as fair as their semaphores' queuing discipline (FIFO helps), a caveat
  the analysis tables flag explicitly.
- Real-system mapping: fixed-size request batching, commits needing M writes
  plus one acknowledgment, team-of-exactly-K matchmaking, and fixed-group
  fork/join phases all share this exact-ratio rendezvous shape.

## When to apply / trade-offs
Use this pattern whenever progress requires an exact multiset of participants
— not "at least" but "exactly" — assembled before any of them may continue.
Prefer the barrier + admission-semaphore composition where a reusable barrier
with a completion hook exists; it is the most legible statement of intent.
Fall back to the semaphore-only emulation for portability, accepting more
intricate counter bookkeeping and the subtle "completing thread coordinates
and does not itself wait" rule. In both designs the sequential-groups
constraint is a throughput ceiling: only one group forms at a time, which is
the point, but variations allowing parallel group formation exist if that
ceiling hurts.

## Fidelity check
1. Claim: permits for the next group are issued only after the current group
   completes. Support: the capture emphasizes that the semaphore refill runs
   inside the barrier's completion action rather than as each thread exits,
   so the next group cannot begin until the current one is fully done.
2. Claim: the naive counter design can strand a group member. Support: the
   capture walks a scenario where three threads all observe the ready
   condition, two decrement first, and the third then re-tests a now-false
   condition and cannot proceed — or multiple rare-kind threads all admit
   themselves into one group.
3. Claim: in the semaphore-only variant the quota-completing thread acts as
   coordinator and skips its own wait. Support: the capture states that the
   thread whose arrival completes the required counts releases the group's
   permits including its own, which is consumed by the release path rather
   than by a blocking acquire.
