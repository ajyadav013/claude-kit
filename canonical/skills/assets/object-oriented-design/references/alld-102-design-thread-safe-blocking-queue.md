---
source: https://algomaster.io/learn/concurrency-interview/design-thread-safe-blocking-queue
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Bounded blocking queue: condition variables done right, then two locks

## What it teaches
Why a bounded blocking queue is the backbone of producer-consumer systems and
how to build one that neither loses items nor strands sleeping threads. The
two guarantees that distinguish it from a plain queue are backpressure
(producers sleep when the buffer is full, so memory cannot be exhausted) and
no busy-waiting (consumers sleep when it is empty instead of spinning). The
underlying store is a fixed circular array with head and tail indices that
wrap modulo capacity, plus an explicit element count because head==tail is
ambiguous between empty and full.

The heart of the chapter is the condition-variable discipline, taught through
four failure modes. Lost wakeup: a consumer observes "empty," and before it
actually parks, a producer inserts and fires its signal into the void; the
consumer then sleeps forever on an already-true condition — the fix is that
the condition check and the wait must happen atomically under the same lock
the signaler holds. Spurious wakeup: threading runtimes are documented to
wake waiters with no signal at all, so code that treats "I woke up" as "the
condition holds" will pop from an empty buffer. Thundering contention: when
one slot frees up, several blocked producers may wake and only one can claim
it; the rest must re-check and re-sleep. All three converge on one rule:
always wait inside a loop that re-tests the predicate, never behind a single
if. The fourth question — signal while still holding the lock, or after
release — is presented as a real trade: under-lock signaling can never lose
a wakeup but makes the woken thread immediately bump into the still-held lock.

Design one uses a single lock plus two condition variables ("space available"
for producers, "items available" for consumers). It is simple, deadlock-free,
and fair with a fair lock, but a producer touching the tail blocks a consumer
touching the head. Design two — the pattern behind the JDK's linked variant —
exploits the fact that producers and consumers touch disjoint ends: separate
put-lock and take-lock, an atomic counter replacing lock-protected count, and
cascading cross-signals: an insert that lifts the queue off empty must
briefly grab the take-side lock to wake consumers, and a removal that opens
space in a previously full queue grabs the put-side lock to wake producers.
Blocking calls must also honor interruption so a stuck thread can be
cancelled.

## Key patterns & decisions
- Bounded capacity as backpressure: a full queue slows producers instead of letting memory grow without limit.
- Circular array with wrap-around indices and a separate count to disambiguate full from empty without shifting elements.
- Predicate re-check loop around every condition wait — the single rule that defuses lost, spurious, and competitive wakeups.
- Two condition variables on one lock, one per direction, so producers and consumers wake only their counterparts.
- Two-lock (head/tail) split for concurrent put+take, justified because the two ends touch disjoint state.
- Cascading signals across locks, triggered only on the empty→nonempty and full→notfull edge transitions detected via the atomic count.
- Interruption-aware blocking so waits are cancellable rather than indefinite.

## When to apply / trade-offs
Single-lock is the right answer for small buffers, low concurrency, and as
the correctness baseline — and the recommended interview lead, since it
showcases condition variables and spurious-wakeup handling. The two-lock
variant buys real throughput when distinct producer and consumer pools hammer
the queue, at the price of linked-node allocation (losing the array's cache
friendliness), cross-lock signaling latency, and correctness that is genuinely
harder to argue. Lock-free queues sit beyond both: maximal concurrency,
usually unbounded, only approximately sizable, and reserved for extreme
performance needs. In production, use the platform's stock bounded queues
rather than hand-rolling.

## Fidelity check
- Claim: the lost-wakeup bug happens in the gap between a consumer's emptiness check and its park. Support: the capture's first challenge describes the producer signaling while no thread is yet waiting, after which the consumer waits forever despite items being present.
- Claim: waiting must be loop-guarded, not if-guarded. Support: the capture's producer-race walkthrough shows multiple producers waking for one freed slot, with the losers needing to re-test and re-sleep, and explicitly states the wait belongs in a loop.
- Claim: the two-lock design signals across locks only on edge transitions. Support: the capture's cascading-signal recipe has a put signal consumers only when the atomic count was zero before increment, and a take signal producers only when the count was at capacity before decrement.
