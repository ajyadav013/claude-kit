---
source: https://algomaster.io/learn/concurrency-interview/signaling-pattern
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# One-way thread signaling with zero-initialized semaphores

## What it teaches

How a thread reliably tells another thread "you may proceed now" without any
handshake in the reverse direction. The chapter's core argument is that naive
notification schemes are fragile because a notification sent before anyone is
listening simply vanishes; the fix is to build the signal out of a primitive
that stores state — a counting semaphore whose permit count survives until
someone claims it. The canonical construction is a semaphore created with a
count of zero: the waiting thread tries to take a permit and suspends (the OS
parks it, so no CPU is burned polling); the signaling thread, when its work is
done, deposits a permit and keeps going without ever blocking itself. Because
the deposit persists in the counter, the ordering of "signal" and "wait" no
longer matters — a waiter arriving late finds the permit already there.

The chapter also frames signaling as the atom underneath most higher-level
coordination constructs: barriers, latches, producer-consumer handoffs, and
thread-pool "worker finished, feed me more" flows are all compositions of this
one-way notify.

## Key patterns & decisions

- **Zero-initialized semaphore as a durable signal**: start the count at 0 so
  the gate is closed by default; the waiter blocks on take, the signaler
  deposits exactly when the precondition is satisfied. Starting at 1 by
  mistake lets the waiter sail through before the work is done — a classic
  bug the chapter calls out explicitly.
- **Signal persistence beats condition variables for one-shot events**: a
  semaphore permit deposited with nobody waiting is retained in the count; a
  condition-variable notify with nobody waiting is discarded. For simple
  "event happened" flags, the semaphore removes an entire class of
  lost-wakeup timing bugs.
- **Asymmetric roles**: the signaler's deposit never blocks; only the waiter
  can block. This decoupling means the signaler need not know whether, or
  when, the waiter shows up.
- **Initialization gate (one-to-many)**: N workers each block on one take;
  the main thread finishes setup and deposits N permits, releasing every
  worker exactly once. Prevents workers from touching a half-built shared
  resource.
- **Ping-pong alternation with two semaphores**: strict turn-taking between
  two threads uses one semaphore per direction, initialized asymmetrically
  (one open, one closed). Both open races; both closed deadlocks — the
  asymmetry *is* the mechanism.
- **Semaphore vs mutex is an ownership question**: a mutex is locked and
  unlocked by the same thread to protect data; a signaling semaphore is
  released by a different thread than the one that acquires, to communicate
  an event. If cross-thread release is needed, a mutex is the wrong tool.
- **Blocking wait over busy polling**: the parked waiter consumes no cycles;
  correctness and efficiency come from letting the scheduler suspend it.

## When to apply / trade-offs

Reach for semaphore signaling when the condition is a simple one-shot event
("initialization finished", "data ready") and the notifying thread is not the
one that will consume the notification. Prefer condition variables instead
when the wait is over an arbitrary predicate that must be re-checked (queue
below a threshold, compound state), accepting the extra protocol burden of an
associated mutex and a re-check loop against spurious wakeups. The trade-off
axis is simplicity-plus-persistence (semaphore) versus predicate flexibility
(condition variable). The most dangerous knob is the initial count: it encodes
whether the gate starts open or closed, and getting it wrong silently defeats
the coordination rather than failing loudly.

## Fidelity check

1. Claim: a permit deposited before anyone waits is not lost. Supported: the
   capture describes the release bumping the internal count from zero to one
   and a later-arriving waiter finding that stored permit immediately, in
   contrast to condition variables where an unheard notify disappears.
2. Claim: initializing the semaphore to 1 instead of 0 is a named common bug.
   Supported: the capture walks through the failure — the waiter's acquire
   succeeds instantly and it proceeds before initialization completes,
   defeating the coordination — and tells readers to always start at zero for
   signaling.
3. Claim: alternating two threads requires two semaphores with asymmetric
   initial values. Supported: the capture's ping-pong section states that
   both-at-1 causes a race over who runs first while both-at-0 deadlocks, and
   that the one-open/one-closed setup passes control back and forth like a
   baton.
