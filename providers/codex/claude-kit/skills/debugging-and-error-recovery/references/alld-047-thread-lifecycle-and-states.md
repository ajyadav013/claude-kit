---
source: https://algomaster.io/learn/concurrency-interview/thread-lifecycle-and-states
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Reading a thread's state machine to debug hung concurrent programs

## What it teaches

A thread is a small state machine — created, eligible to run, actually on a
core, parked on a lock, parked waiting for a signal (with or without a
deadline), and finally dead. The article's practical point is diagnostic:
when a multithreaded app hangs, the fastest route to a root cause is asking
"what state is each thread in, and what transition is it stuck waiting for?"
It also surveys how differently languages expose this machine, from Java's
rich six-value enum down to Go's deliberate refusal to expose goroutine state
at all.

## Key patterns & decisions

- **Four universal OS-level states**: ready (runnable, no core yet), running
  (on a core), blocked (waiting on I/O, a lock, or an event), terminated.
  Language-level state enums are refinements of these, so any language's model
  can be mapped back to this base when reasoning about a hang.
- **BLOCKED vs WAITING as distinct diagnoses**: blocked means contending for a
  mutex/monitor someone else holds (fix: reduce contention, check lock
  ordering); waiting means deliberately parked until another thread signals
  (fix: find the missing notify/send/completion). Conflating the two sends you
  hunting the wrong bug.
- **Deadlock detection via state introspection**: in runtimes with queryable
  states (e.g. Java's per-thread state enum), a deadlock shows up as a cycle of
  threads all in the lock-blocked state waiting on each other — you can detect
  it programmatically, not just by staring at a hang.
- **Timed waits as a hang-avoidance discipline**: the timed-waiting state
  (sleep/wait/join with a deadline) exists precisely so a thread wakes on
  timeout even if the expected signal never arrives; unbounded waits are where
  forever-hangs live.
- **RUNNING vs RUNNABLE is unobservable from user space**: by the time a state
  query returns, the scheduler may have preempted and resumed the thread
  several times, which is why most language APIs collapse the two into one
  "alive and not blocked" notion. Don't build logic that tries to distinguish
  them.
- **Go's anti-introspection stance as a design pattern**: goroutines expose no
  state API on purpose — the runtime pushes you to structure completion via
  channels, wait groups, and context cancellation instead of polling another
  task's state. State-polling designs are a smell; communicate outcomes
  instead.
- **Terminated is terminal**: a finished thread's OS resources are gone and it
  can never be restarted; the language object may linger, but re-starting it is
  an error. Pools reuse live threads, not dead ones.
- **Transition-table thinking**: every state change has a named trigger
  (start call, scheduler dispatch, time-slice expiry, lock acquisition, signal,
  timeout, completion/uncaught exception). Enumerating the trigger that should
  have fired but didn't is the systematic way to localize a stall.

## When to apply / trade-offs

Use this model whenever a concurrent program hangs, burns CPU without
progress, or ends before its workers finish: take a thread dump (or the
runtime's equivalent), bucket threads by state, and look for lock-blocked
cycles, indefinite waiters missing their signal, or a main thread that never
joined its workers. The trade-off across languages is introspection power vs
design pressure: rich state APIs (Java, C#) make post-hoc debugging easier but
tempt state-polling designs; minimal APIs (Python's alive check, C++'s
joinable check) force external tooling; Go trades introspection away entirely
to push you toward channel/waitgroup structure that hangs less in the first
place.

## Fidelity check

1. Claim: blocked-on-lock and waiting-for-signal are semantically different
   states. Support: the capture distinguishes the blocked state (trying to
   enter a lock-protected region another thread owns) from the waiting state
   (explicitly parked until signaled, e.g. via wait/join/park or a channel
   receive), noting the blocked thread competes for access while the waiting
   thread just sleeps until woken.
2. Claim: user code cannot reliably tell "running" from "ready". Support: the
   capture explains the distinction exists only at OS level and that by the
   time a state query answers, preemption may have happened repeatedly, so
   Java, C#, Python, and Go all merge the two.
3. Claim: Go intentionally exposes no goroutine state. Support: the capture
   states there is no state getter or enum for goroutines by design, and that
   the intended substitutes are channels for completion, wait groups for
   joining, and context for cancellation.
