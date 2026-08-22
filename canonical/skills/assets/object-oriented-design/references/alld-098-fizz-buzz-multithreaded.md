---
source: https://algomaster.io/learn/concurrency-interview/fizz-buzz-multithreaded
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Condition-based thread dispatch: four handlers, one ordered stream

## What it teaches
Four specialized threads each own one output class (multiple-of-3 word,
multiple-of-5 word, multiple-of-15 word, plain numbers), and a strictly
ordered stream of values must be routed so exactly one thread acts per value.
The chapter frames this as the "conditional activation" problem: unlike plain
alternation, eligibility is computed from a property of the current item, the
eligibility rules overlap (15 satisfies both the 3-rule and the 5-rule), and
the workloads are wildly uneven. Its deepest lessons are about the controller
pattern — after acting, the current thread computes who is eligible next and
signals only them — and about clean termination, which requires a final
wake-everyone broadcast so idle handlers can observe the end condition and
exit instead of hanging.

## Key patterns & decisions
- Post-action dispatch chain: each thread, after handling its item, advances
  the shared counter, evaluates the next item's class, and releases exactly
  that thread's semaphore. At all times exactly one permit exists in the
  system, which simultaneously guarantees ordering and deadlock freedom.
- Specificity-ordered classification: test the most restrictive predicate
  first (divisible by 15 before 3 or 5), because the broader predicates also
  match the special case and would misroute it. The article calls this the
  most common interview mistake.
- Termination broadcast: when the counter passes n, release every semaphore
  (or notify every condition) so all parked handlers wake, observe completion,
  and exit; forgetting this "everyone go home" step guarantees a hang because
  most handlers are still waiting when the last item is processed.
- Loop-until-done, not loop-a-fixed-count: because workloads are asymmetric
  (for n=15 the plain-number thread acts eight times, the 15-thread once),
  each thread must loop on the global completion condition rather than a
  precomputed iteration count.
- Check-then-act on an atomic counter is still racy: two threads can both read
  the same stale value, both find their predicate true, and both act; an
  atomic increment does not retroactively fix a decision made on a stale read.
- Broadcast-predicate alternative: one lock, one condition, each thread waits
  on "my class matches OR stream finished," and each action ends with a
  notify-all. Simpler bookkeeping, but three wasted wakeups per item.
- Hybrid of one condition variable per thread plus a dispatch helper recovers
  targeted wakeup with condition-variable semantics; a barrier-per-step
  variant exists but is overkill since only one thread needs to act per step.
- Extensibility argument for the dispatch chain: adding a fifth output class
  means one more semaphore and one more branch in the dispatcher, whereas the
  broadcast design requires re-deriving every thread's predicate.

## When to apply / trade-offs
This is the go-to shape for type-based routing under a strict ordering
constraint: event routers, protocol-type packet handlers, URL-pattern load
balancing, specialized workers on a shared queue. Choose the semaphore
dispatch chain when throughput matters or handler count may grow; choose the
single-condition broadcast when n is small and simplicity wins. Whatever the
mechanism, two details are non-negotiable: overlapping predicates must be
checked most-specific-first, and shutdown must wake every parked handler.

## Fidelity check
1. Claim: exactly-one-permit is the invariant that yields both ordering and
   liveness in the dispatch-chain design. Support: the capture's analysis
   table attributes correct ordering to only one thread proceeding at a time
   and deadlock freedom to there always being exactly one permit present.
2. Claim: termination needs a release-all step. Support: the capture's n=5
   trace ends with the buzz-side thread advancing the counter past n and
   releasing all four semaphores so every thread can check the end condition
   and exit, and the challenge section says omitting this hangs the program.
3. Claim: the naive spin version is broken even with atomics. Support: the
   capture describes two threads both reading the same counter value, both
   deciding to act, and notes the atomic increment cannot help because the
   eligibility decision used a stale read.
