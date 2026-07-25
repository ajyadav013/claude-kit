---
source: https://algomaster.io/learn/concurrency-interview/reentrant-locks
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Reentrant locks: letting a thread re-enter its own critical section

## What it teaches

A reentrant (recursive) lock permits the thread that already holds it to acquire
it again without blocking. Internally it tracks two things a plain binary lock
does not: the identity of the owning thread and a hold count. Each nested acquire
by the owner bumps the count; each release decrements it; the lock only becomes
available to other threads when the count returns to zero. The ownership check —
"is the requester the thread that already owns me?" — is the entire mechanism:
without it, a re-acquiring owner just sees "held" and deadlocks on itself.

The chapter motivates reentrancy with three recurring shapes of self-deadlock.
First, recursive algorithms: a synchronized tree walk that locks per node and then
recurses would, under a non-reentrant lock, wait forever for a lock its own outer
frame holds. Second, method composition: a public method that locks internally
gets called from another method of the same object that already holds the lock —
e.g., a deposit operation whose logging path reads the balance through a public,
independently-lockable getter. Third, callbacks: an event dispatcher iterating its
listener list under a lock cannot control whether a handler calls back in to
register another listener; reentrancy keeps that re-entry from deadlocking
(though mutating a collection mid-iteration remains a separate hazard needing its
own fix, such as iterating a copy).

Release discipline matters symmetrically: every acquire must be matched by exactly
one release. Under- releasing leaves the count above zero forever, silently
blocking all other threads; releasing from a non-owner thread is an outright error
that mainstream runtimes reject with an exception. Java's synchronized blocks are
implicitly reentrant with automatic release; explicit reentrant lock objects trade
that convenience for try/finally responsibility plus extras like try-lock,
timeouts, fairness, and an inspectable hold count for debugging.

## Key patterns & decisions

- Owner-plus-count lock state: reentrancy = remembering who holds the lock and how
  many times; re-acquisition by the owner is a cheap counter bump, not a block.
- Balanced acquire/release invariant: unlock exactly as many times as you locked —
  an unmatched pair leaves the lock permanently half-held with no error raised.
- Reentrancy for method composition: public methods that lock internally can be
  safely invoked both externally and from other lock-holding methods of the same
  object, without a locked/unlocked duplicate of every method.
- Reentrancy for recursive synchronized algorithms: each recursion level nests an
  acquisition; the structure unwinds naturally as the stack returns.
- Callback-under-lock tolerance: dispatchers that fire user code while locked
  survive handlers that re-enter the locking API — while noting reentrancy fixes
  the deadlock, not concurrent-modification-during-iteration.
- Fail-fast non-owner release: rejecting unlock from a thread that is not the
  owner converts a silent corruption into an immediate, debuggable error.
- Non-reentrant as a deliberate strictness choice: choosing the stricter lock
  makes accidental self-re-acquisition fail loudly, useful when re-entry would
  indicate a design bug and in ultra-hot paths where the ~quarter overhead counts.
- Reentrant as the safe default: the bookkeeping overhead is nanoseconds and
  dwarfed by real contention costs; default to reentrant unless profiling says
  otherwise.

## When to apply / trade-offs

Choose reentrant locks whenever lock-holding code can call other code that locks:
composed methods, recursion, observer/plugin callbacks — or simply when unsure,
since surprise self-deadlock costs far more debugging time than the small constant
overhead (roughly a quarter more per lock/unlock and ~half again the per-lock
memory, per the chapter's figures, with the reentrant fast path itself only a few
nanoseconds). Choose non-reentrant when critical sections are leaf-level and
brief, when every cycle in a hot path matters, or when you want re-entry to
surface immediately as a bug rather than silently succeed. Regardless of flavor,
explicit lock objects demand the try/finally release pattern, and hold-count
introspection is a practical debugging aid for verifying balanced usage.

## Fidelity check

1. Claim: the lock is only released to other threads when the hold count reaches
   zero, so mismatched acquire/release counts strand waiters forever. Support: the
   capture's release-logic walkthrough shows a decrement from two to one leaving
   the lock held with no waiters woken, and explicitly calls out lock-twice/
   unlock-once as a permanent block for other threads.
2. Claim: unlocking from a thread that does not own the lock is treated as an
   error, not a no-op. Support: the capture states this raises
   IllegalMonitorStateException in Java and RuntimeError in Python as the first
   check in the release path.
3. Claim: reentrant acquisition is much cheaper than a fresh contended path, and
   overall overhead versus non-reentrant locks is modest. Support: the capture's
   performance table puts uncontended lock/unlock around 20–25ns with roughly 25%
   reentrant overhead, the reentrant re-acquisition itself near 5ns, and memory
   per lock rising from about 32 to about 48 bytes.
