---
source: https://algomaster.io/learn/concurrency-interview/print-zero-even-odd
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Three-thread coordination with a dispatcher: asymmetric turn-taking

## What it teaches
This problem upgrades two-party alternation to a three-party arrangement with
unequal roles: one "separator" thread must run before every value, while two
value-producing threads alternate between themselves. The output pattern
(zero, one, zero, two, zero, three, ...) forces one thread to act as a
coordinator that decides, after each of its own turns, which worker goes next.
The chapter's core lesson is that multi-party ordering is a state machine —
here with four states, because the coordinator's "before odd" and "before
even" situations are genuinely distinct — and that the coordinator needs a
targeted signaling mechanism, not a broadcast, to route control correctly.
It also surfaces the bookkeeping cost of unequal iteration counts: the
coordinator runs n times while the two workers split roughly half each.

## Key patterns & decisions
- Coordinator/worker dispatch: give every thread its own semaphore; the
  coordinator, after acting, inspects its loop counter's parity and releases
  exactly one worker's semaphore, while workers unconditionally hand control
  back to the coordinator. Decision logic concentrates in one place.
- One shared wait-point per role is a routing bug: if both workers block on
  the same semaphore, either may grab the permit, so the wrong worker can run.
  Distinct wakeup channels are what make dispatch deterministic.
- Model the ordering as an explicit four-state machine (coordinator-before-A,
  A, coordinator-before-B, B); enumerating states first makes both the
  semaphore and the condition-variable designs mechanical to derive.
- Single condition variable + broadcast is the simpler-but-wasteful variant:
  all threads share one condition, each waits on its own predicate over the
  state enum, and every transition wakes everyone. Correct, but two of three
  wakeups are wasted, and the waste grows with participant count.
- Hybrid: separate condition variables per role restore targeted wakeup while
  keeping condition-variable semantics (predicate re-check on spurious wakeup).
- Derive per-thread loop bounds from the sequence, not by symmetry: for n
  items the odd worker runs ceil(n/2) times and the even worker floor(n/2);
  early-finishing workers must not wedge the still-running ones.
- The article maps the shape onto real systems: an I/O selector fanning out to
  type-specific handlers, a producer routing items to chosen consumers, and
  round-robin scheduling by a central coordinator.

## When to apply / trade-offs
Use the coordinator-with-per-worker-semaphores shape whenever one component
must interleave and route between several others in a data-dependent order —
event demultiplexers, routing producers, protocol dispatchers. The broadcast
condition-variable variant is acceptable at three threads and gets steadily
worse as the crowd grows, so treat targeted wakeup as the default for anything
that scales. The spin-on-shared-state baseline is again correct but burns at
least two cores' worth of useless polling with three threads. Watch the edge
cases created by uneven work distribution: termination must be reasoned about
per role, not once globally.

## Fidelity check
1. Claim: the coordinator picks which worker to wake using the parity of its
   own iteration counter. Support: the capture explains that when the counter
   is odd the next printed value is odd so the odd-side semaphore is released,
   and even counters release the even-side semaphore.
2. Claim: sharing one semaphore between both workers is unsafe. Support: the
   capture describes that with a single number-side semaphore either worker
   could acquire the released permit, letting the even worker run when the odd
   value is due, producing wrong output.
3. Claim: the broadcast variant trades efficiency for simplicity. Support: the
   capture notes that waking all three threads means two re-check a false
   predicate and sleep again — tolerable at three participants but poorly
   scaling to many.
