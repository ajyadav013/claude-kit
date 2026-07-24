---
source: https://algomaster.io/learn/concurrency-interview/condition-variables
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Condition variables: sleeping until a predicate becomes true

## What it teaches

A condition variable lets a thread park itself until some arbitrary boolean
predicate over shared state becomes true, instead of burning a core polling for
the change. The chapter frames the primitive as a separation of two concerns: a
mutex protects the shared state itself, while the condition variable provides the
efficient wait-for-change mechanism. Neither alone is sufficient — a mutex without
a wait mechanism forces busy-waiting; waiting without mutual exclusion races.

The load-bearing mechanism is the atomic release-and-sleep inside the wait call:
the caller must hold the mutex, and wait atomically releases that mutex while
enqueueing the thread on the wait queue as one indivisible step. This closes the
window in which a naive check-then-sleep sequence can miss a signal fired between
the check and the sleep — the "lost wakeup" bug, which typically stays hidden
under light load and only hangs the program under production timing. Signals do
not persist or queue; a signal with no waiter present is simply gone.

The other structural rule the chapter drills: always recheck the predicate in a
while loop around wait, never an if. Being signaled only moves a thread to a
transient "must reacquire the mutex" state; by the time it actually runs, another
thread may have consumed the state change (and spurious wakeups exist), so the
condition must be verified again after every wakeup.

The worked example is the bounded buffer with two condition variables sharing one
lock — one predicate for "space available" (producers wait) and one for "items
available" (consumers wait) — plus a from-scratch semaphore built on a condition
variable, showing how higher-level primitives compose from lower-level ones.

## Key patterns & decisions

- Mutex-guarded predicate wait: every wait happens while holding the lock that
  protects the predicate's state; the atomic unlock-and-enqueue is what prevents
  lost wakeups.
- While-loop recheck, never if: signaled threads must revalidate the predicate
  after reacquiring the mutex, because the world can change in the signaled-but-
  not-yet-running window and spurious wakeups occur.
- Signals are ephemeral: notification wakes only threads already waiting; it
  carries no data and leaves no trace, so state changes must be recorded in shared
  variables the woken thread inspects.
- One lock, multiple conditions: partition waiters by predicate (not-full vs
  not-empty) so each state change wakes only threads that can actually proceed.
- Signal-one vs broadcast-all: wake one thread when exactly one can make progress;
  broadcast only when many can proceed or during shutdown — indiscriminate
  broadcast causes the thundering-herd stampede of futile wakeups and lock churn.
- Post-wakeup serialization awareness: every woken thread must reacquire the mutex
  one at a time, so mass wakeups create a lock-convoy bottleneck by construction.
- Unlock-before-notify micro-optimization: releasing the mutex before signaling
  spares the woken thread an immediate block on a still-held lock (minor on modern
  schedulers, but harmless).
- Primitive composition: a counting semaphore falls out naturally from a mutex,
  one condition variable, and a counter — a standard interview construction.

## When to apply / trade-offs

Use condition variables wherever a thread must wait for a state change it cannot
predict: producer-consumer queues, thread-pool workers idling for tasks, barriers,
one-time initialization gates, and pool-resource availability. The alternative —
spin-polling — wastes CPU, scales terribly with waiter count, can starve the very
producer being waited on, and costs real money at datacenter scale. The main
tuning decisions are signal granularity (one vs all) and condition partitioning
(more conditions per lock reduce futile wakeups at a small complexity cost). For
extremely hot paths, lock-free structures may beat condition-variable coordination,
but they trade away the simplicity and generality of the arbitrary-predicate model.

## Fidelity check

1. Claim: the wait operation releases the mutex and enqueues the thread as one
   atomic step, and this atomicity is what prevents lost wakeups. Support: the
   capture's internals walkthrough states the enqueue and the mutex release happen
   as a single indivisible action, and its race-condition trace shows a signal
   vanishing when a consumer decided to wait but had not yet entered the queue.
2. Claim: a woken thread does not resume user code immediately — it must first win
   the mutex back, which is why the predicate must be rechecked in a loop.
   Support: the capture describes the signaled state as transient, notes the
   signaler may still hold the mutex when it notifies, and ties the mandatory
   while-loop recheck to this reacquisition gap.
3. Claim: the bounded buffer uses two conditions on one lock specifically for
   wakeup efficiency. Support: the capture's design discussion says a single
   condition with broadcast would rouse threads that cannot proceed (e.g., waking
   every producer when only one slot opened), whereas separate not-full/not-empty
   conditions target exactly the threads that can act.
