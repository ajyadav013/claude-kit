---
source: https://algomaster.io/learn/concurrency-interview/semaphores
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Semaphores: counting permits to bound concurrency

## What it teaches

A semaphore is a synchronization primitive whose whole job is to answer "how many
threads may proceed right now?" It keeps an integer permit count and exposes two
atomic operations: one that takes a permit (blocking the caller when the count is
zero) and one that hands a permit back (waking a blocked waiter if one exists).
The release side never blocks; only acquisition can. The chapter grounds this in
Dijkstra's original 1965 formulation — the P/V naming derives from Dutch verbs for
"test" and "increment" — and stresses that the atomicity of the check-and-modify
step is what makes the primitive safe.

Two flavors exist. A binary semaphore (one permit) toggles between available and
taken, and is best used as a signaling gate between threads. A counting semaphore
(N permits) admits up to N concurrent holders and is the natural fit for pooled
resources: database connection pools, capping in-flight API calls, limiting open
file handles, or sizing parallel work to the number of CPU cores.

The chapter's most interview-relevant material is the semaphore-versus-mutex
contrast. A mutex has an owner — only the locking thread may unlock, which is what
enables priority inheritance, deadlock detection, and unlock-by-wrong-thread error
checks. A semaphore deliberately has no owner: any thread may release, which is
precisely what makes asymmetric producer/consumer signaling possible (one thread
only ever releases, another only ever acquires — an error under mutex semantics,
the intended pattern under semaphore semantics).

## Key patterns & decisions

- Permit-counting admission control: gate concurrent access to N interchangeable
  resources with an N-permit counting semaphore instead of ad-hoc counters.
- Ownerless release enables signaling: because any thread may release, semaphores
  support cross-thread event notification that mutexes forbid by design.
- Acquire-then-try/finally-release discipline: guarantee the permit is returned on
  every exit path, including exceptions, or the pool silently shrinks (permit leak).
- Two-semaphore bounded buffer: one semaphore counts empty slots (producers wait on
  it), one counts filled slots (consumers wait on it) — the classic coordination
  recipe.
- Non-blocking acquisition for graceful degradation: a try-acquire variant (with or
  without timeout) lets callers fall back to an alternative path instead of queueing.
- Fair vs non-fair trade-off: FIFO fairness prevents starvation at a throughput
  cost; the default barging mode maximizes throughput but can starve long waiters.
- Right tool selection over reflexive semaphore use: plain mutual exclusion wants a
  mutex; a lock-free counter wants an atomic; one-shot readiness wants a latch;
  precise rate control wants a token bucket (better burst behavior).
- Permit-count sizing as a tuning knob: match permits to the real resource limit
  (pool size, core count) — too few blocks needlessly, too many defeats the cap.

## When to apply / trade-offs

Reach for a counting semaphore whenever a fixed pool must not be oversubscribed and
callers can tolerate waiting. Prefer a mutex for protecting shared mutable state:
its ownership model buys priority inheritance and better error detection, and the
"only one may enter" intent reads more clearly. Cost-wise, uncontended semaphore
operations are tens of nanoseconds; a contended acquire that must sleep costs
microseconds because of the context switch, so under heavy contention the queueing
itself becomes the bottleneck. Fairness is a policy decision, not a default:
enable it for user-facing latency or starvation-prone workloads, skip it when raw
throughput dominates. For pure rate limiting, a semaphore caps concurrency but not
rate — a token bucket regulates requests per second more smoothly.

## Fidelity check

1. Claim: the release operation never blocks, only acquisition does. Support: the
   capture's walk-through of the two operations states release always completes
   immediately, incrementing the count and optionally waking one waiter, while
   acquire alone can put the caller to sleep when permits are exhausted.
2. Claim: mutexes carry ownership semantics that semaphores lack, and this is the
   decisive practical difference. Support: the capture's comparison table lists
   ownership as yes-for-mutex/no-for-semaphore and explains that ownership enables
   priority inheritance and error checking, while ownerless release enables
   producer/consumer signaling where acquirer and releaser are different threads.
3. Claim: the P/V terminology traces to Dijkstra's 1965 paper and Dutch words for
   testing and incrementing. Support: the capture explicitly attributes the names
   to "proberen" and "verhogen" from Dijkstra's original paper introducing the
   primitive.
