---
source: https://algomaster.io/learn/concurrency-interview/mutex
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Mutexes: ownership semantics, contention economics, and lock hygiene

## What it teaches

The mutex is the base synchronization primitive: one holder at a time, blocked
waiters parked off-CPU, and — the property people forget — ownership, meaning
the locking thread is the only legitimate unlocker. The article covers the
lock lifecycle (unlocked → locked → waiters queued → release wakes one waiter
who must re-compete), the operation set (blocking acquire, release, try-lock,
try-lock-with-timeout), the exception-safe release discipline, and, most
usefully for practitioners, the economics of contention: an uncontended lock
costs nanoseconds while a contended one costs microseconds, so the real
engineering work is keeping contention low.

## Key patterns & decisions

- **Ownership as a defining property**: unlike a plain semaphore, a mutex is
  released only by the thread that acquired it; designs where one thread locks
  and another unlocks are misusing the primitive.
- **Wake-up does not mean acquisition**: releasing wakes one parked waiter,
  but that waiter re-runs the availability check and may lose to a thread that
  arrived in the meantime — code after a wake must re-attempt, never assume
  ownership.
- **Guaranteed-release discipline**: pair every acquire with a release on all
  exit paths (the acquire-before-try / release-in-finally shape, or a
  language construct that scopes the lock automatically); acquiring inside the
  protected block risks releasing a lock you never obtained when acquisition
  itself fails.
- **Blocking vs try-lock vs timed try-lock**: choose the blocking acquire for
  ordinary sections, the immediate try variant when you can do useful work on
  failure, and the timed variant to bound worst-case waiting and enable
  deadlock back-off.
- **Contention cost hierarchy**: an uncontended acquire/release is a few
  atomic instructions (order of tens of nanoseconds); once the scheduler must
  park and wake threads it's microseconds; heavy waiter queues cost tens to
  hundreds of microseconds — a 100-1000x penalty that turns a hot lock into a
  serialization point where a many-core box degrades to single-core throughput.
- **Shrink the critical section first**: holding the lock for the minimum
  instructions (never across I/O or slow computation you could hoist out) is
  the single highest-leverage contention fix.
- **Split locks by data, not convenience**: independent data should have
  independent locks (finer granularity raises throughput), at the price of
  needing a global lock-acquisition order to avoid deadlock once multiple
  locks exist.
- **Escalation ladder past the mutex**: atomics for single-word counters and
  flags (no blocking at all, though memory-ordering rules still cost
  something); read-write locks when reads vastly outnumber writes and are not
  so short that lock overhead dominates; sharded locks, lock-free structures,
  or thread-local caching for genuinely hot paths.
- **Join before reading results**: the coordinating thread must wait for
  workers to finish before consuming shared totals, or it reads a
  still-changing value — completion synchronization is part of correctness,
  not just the lock.

## When to apply / trade-offs

Default to a mutex for any multi-step invariant over shared mutable state; it
is simple, general, and cheap when uncontended. Move up the ladder only on
measured contention: first shrink the held region, then split the lock, then
consider atomics or read-write locks for the specific access pattern. Beware
the read-write lock's fine print — it pays off only with a strongly
read-dominated mix, non-trivial read durations, and a writer rate low enough
to avoid starvation in either direction. Language-level intrinsic locking
(automatic release, less to get wrong) versus explicit lock objects (try-lock,
timeouts, fairness policies) is a simplicity-versus-control trade; take the
simple form unless you need the extra features.

## Fidelity check

1. Claim: contention shifts lock cost by orders of magnitude. Support: the
   capture's cost table puts uncontended lock/unlock at 10-100 ns, a contended
   acquisition involving the OS scheduler at 1-10 us, and many-waiter queue
   management at 10-100 us, summarizing the trend as a 100-1000x penalty.
2. Claim: a single hot lock serializes a multicore machine. Support: the
   capture's worked scenario is a web server with 100 threads sharing one
   cache mutex at ~1 ms per use — under load 99 threads sit blocked while one
   works, making the system behave like a single-core pipeline at that lock.
3. Claim: a woken waiter may still fail to acquire. Support: the capture's
   step-by-step acquisition flow says the notified thread loops back to the
   availability check and may compete with newly arrived threads, so waking
   grants another attempt, not the lock itself.
