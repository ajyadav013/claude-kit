---
source: https://algomaster.io/learn/concurrency-interview/print-foobar-alternately
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Two-thread strict alternation: the ping-pong handoff problem

## What it teaches
This is the minimal turn-taking synchronization exercise: two concurrently
scheduled threads must interleave their outputs in a fixed A-B-A-B order for n
rounds, with no interleaving decided by the OS scheduler. The chapter uses it
to introduce the three canonical failure modes of naive coordination —
check-then-act races on a shared flag, CPU-burning spin loops, and the lost
wakeup where a notification fires before the receiver has begun waiting — and
then walks through how each mainstream primitive (spin flag, semaphore pair,
mutex + condition variable) addresses or fails to address them. The evaluation
rubric it applies (correct ordering, deadlock freedom, no busy waiting,
simplicity) is a reusable checklist for any coordination design.

## Key patterns & decisions
- Semaphore baton handoff: model turn-taking with two binary semaphores, the
  first-mover's initialized to one permit and the other to zero; each thread
  blocks on its own semaphore and, after acting, releases the peer's. The
  permit-sum invariant (always exactly one permit total) proves mutual
  alternation.
- Sticky permits beat transient signals: a semaphore release performed before
  the peer ever waits is banked, not dropped, which structurally eliminates the
  lost-wakeup hazard that plagues bare condition-variable signaling.
- Condition-variable wait must live in a predicate loop: re-test the turn flag
  after every wakeup (spurious wakeups are legal), hold the lock across both
  the check and the flag mutation, and flip the state before signaling so the
  woken thread observes the new state.
- Busy-wait spin on a shared flag is functionally correct but operationally
  wrong: it starves the very peer that could make progress (worst on a single
  core) and shows up as phantom CPU load in production.
- Yield-in-loop is a documented middle tier between raw spinning and blocking:
  cheaper than a tight spin, costlier than sleeping, useful only where blocking
  primitives are unavailable or too expensive.
- Barriers generalize the pattern to N ordered participants; a two-party
  handoff does not scale by adding more flags, but a barrier at each round does.
- Evaluate every candidate against a fixed four-property scorecard (ordering,
  liveness, CPU efficiency, maintainability) rather than arguing informally.

## When to apply / trade-offs
Reach for the semaphore handoff whenever two components must ping-pong control
in a fixed order — request/response protocol steps, produce-then-consume
pipeline stages, physics-then-render game loops. Prefer condition variables
only when the "may I proceed?" predicate is richer than a permit count, and
accept the extra verbosity and the notify-ordering subtleties that come with
them. Never ship the spin-flag version outside a prototype; it converts idle
waiting into billable CPU. If the cast grows beyond two threads, restructure
around a barrier instead of chaining pairwise handoffs.

## Fidelity check
1. Claim: the semaphore design encodes "first mover goes first" purely through
   initial permit counts. Support: the capture states the foo-side semaphore
   starts at one and the bar-side at zero precisely so foo can proceed
   immediately while bar blocks until released.
2. Claim: semaphores structurally avoid lost wakeups where condition variables
   do not. Support: the capture explains that a released permit is stored and
   later consumed even if release precedes acquire, contrasting this with a
   condition-variable signal that vanishes if sent before the peer waits.
3. Claim: spinning is worst on a single core because it blocks the peer's
   progress. Support: the capture describes the spinning thread monopolizing
   the CPU so the thread that would flip the flag cannot be scheduled until
   preemption, wasting large cycle counts for nontrivial n.
