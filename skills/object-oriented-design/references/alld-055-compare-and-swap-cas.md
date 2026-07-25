---
source: https://algomaster.io/learn/concurrency-interview/compare-and-swap
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Compare-and-swap: the hardware primitive behind lock-free code, and its ABA trap

## What it teaches

Compare-and-swap (CAS) is a single CPU instruction that conditionally updates a memory word:
it takes the address, the value the caller believes is there, and the desired replacement, and
performs the check-then-write as one indivisible step. If the memory no longer matches the
expectation, nothing is written and the caller learns it lost a race. This turns concurrency
control from "block others while I work" into optimistic "attempt, detect conflict, retry" —
the same idea as version-checked saves in a shared document, executed in nanoseconds. The
chapter grounds this in the cache-coherence machinery that makes it atomic across cores,
the retry-loop idiom that makes a single fallible CAS into a reliable update, and the ABA
hazard that makes naive value comparison unsafe for pointer-based structures.

## Key patterns & decisions

- **Optimistic concurrency at the instruction level**: read, compute the new value, then
  attempt an atomic conditional swap; losing a race costs a retry, never a block.
- **The CAS retry loop**: because any single attempt can lose to a concurrent writer, correct
  lock-free updates wrap CAS in a loop that re-reads the current value and recomputes before
  trying again — progress of the system never depends on one specific thread.
- **Cache coherence is what makes it atomic**: the executing core takes exclusive ownership of
  the cache line (invalidating other cores' copies under the coherence protocol) before the
  compare-and-write executes, so no core can slip in between the check and the store.
- **Lock-freedom as a fault-isolation property**: with a mutex, a crashed or wedged lock
  holder strands every waiter; with CAS there is nothing to hold, so a dead thread simply
  stops competing and everyone else proceeds.
- **Weak vs strong CAS**: some architectures offer a cheaper variant that may fail even when
  the value matched (spurious failure); choose the weak form inside retry loops where a
  pointless extra iteration is cheap, and the strong form for one-shot decisions that need a
  definitive answer.
- **The ABA problem**: CAS validates the value, not the history — if a location went from A to
  B and back to A while a thread was paused, that thread's CAS wrongly succeeds; this is
  catastrophic when A is a pointer whose node was freed and reallocated in the interim.
- **ABA defenses**: pair the value with a monotonically increasing version/stamp so a
  round-trip still changes the compared tuple; or manage reclamation so memory cannot be
  reused while readers might hold it (hazard pointers, epoch-based deferred freeing).
- **Contention decides CAS vs locks**: CAS shines with short critical sections and low-to-
  moderate contention and eliminates blocking-induced tail latency; under extreme contention
  or long critical sections, spinning retries can burn more CPU than parking on a lock, and
  locks additionally support things like priority inheritance and simpler reasoning.

## When to apply / trade-offs

Reach for CAS (usually via a language's atomic types rather than hand-rolled loops) for hot,
tiny shared updates: counters, flags, head/tail pointers of lock-free structures. It is the
substrate of mainstream infrastructure — concurrent hash maps, kernel refcounting and
spinlocks, runtime scheduler queues, atomic APIs in Java/C++/Rust/Go. Prefer plain locks when
critical sections are long, contention is severe, or correctness auditing matters more than
nanoseconds. Simple numeric counters are largely ABA-immune (a value that returns to 5 is
still a valid 5), but any design where the compared word is a reusable pointer must adopt a
versioning or safe-reclamation scheme before shipping.

## Fidelity check

1. Claim: the check and the write are indivisible from the perspective of other cores.
   Support: the capture describes the executing core acquiring exclusive access to the cache
   line and forcing other cores to invalidate their copies before the conditional swap runs,
   so no thread can observe a half-done CAS.
2. Claim: weak CAS exists because spurious-failure-free CAS is expensive on some hardware.
   Support: the capture explains that on architectures like ARM a guaranteed-strong variant
   needs extra synchronization, so a loop that will retry anyway should use the cheaper weak
   form.
3. Claim: ABA is mainly a pointer-reuse hazard, not a counter hazard. Support: the capture's
   scenario has a paused thread's CAS succeed on a pointer whose target was popped, freed,
   and reallocated at the same address, while noting that an integer counter cycling back to
   its old value is still semantically valid.
