---
source: https://algomaster.io/learn/concurrency-interview/livelock
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Livelock: busy threads, zero progress — and jitter as the cure

## What it teaches

Livelock is the failure mode where threads never block yet the system accomplishes nothing:
each participant keeps reacting to the others — retrying, yielding, backing off — in perfect
symmetry, like two people in a corridor who repeatedly sidestep in the same direction. It is
arguably sneakier than deadlock because the system looks healthy: CPU is pegged, logs churn
with retry lines, requests are in flight — so hours can pass before anyone notices that
completions have flatlined. The chapter's diagnosis is that livelock is usually born from
well-intentioned resilience code (retries, polite conflict-yielding, synchronized backoff),
and its prescription is to break the symmetry between contenders, chiefly with randomized
backoff, plus asymmetric roles, retry caps, and circuit breakers.

## Key patterns & decisions

- **Livelock vs deadlock diagnostic table**: deadlocked threads show BLOCKED in dumps with
  near-zero CPU; livelocked threads show RUNNABLE with high CPU — the same evidence read
  oppositely, so knowing which signature you are looking at directs the fix.
- **Symmetry is the root cause**: when all contenders back off under the same trigger with
  the same strategy and the same timing, they re-collide indefinitely; fixed-interval retries
  and jitterless collision resolution keep components phase-locked.
- **Thundering herd as a livelock species**: many waiters waking together on one freed
  resource, mostly failing, and re-sleeping in unison recreates the same stampede every
  cycle.
- **Exponential backoff with jitter as the default remedy**: linear backoff preserves
  synchronization outright, plain exponential backoff still keeps same-start threads in
  phase; adding randomness guarantees two identically-timed failures produce different next
  attempts, letting one winner finish first.
- **A menu of jitter formulas**: fully random within the exponential window (max
  desynchronization), half-fixed-half-random (keeps a floor on the wait), or a decorrelated
  scheme where each delay is drawn relative to the previous one (drift grows over time).
- **Asymmetric behavior / priorities**: give contenders unequal roles or backoff aggression
  so someone predictably wins; equality among retriers is precisely what sustains the loop.
- **Cap retries and fail gracefully**: unbounded retrying converts a transient conflict into
  a permanent CPU fire; a maximum-attempt budget turns it into a reportable error.
- **Circuit breaker to stop retry storms**: after sustained failures, refuse further attempts
  outright for a cooling-off period so the underlying system can recover instead of being
  hammered by the recovery logic itself.
- **Detection heuristics**: high CPU with flat throughput, unbounded retry counters, growing
  queues with stalled completions, retries clustering at identical timestamps, and profiles
  dominated by backoff code rather than business logic.

## When to apply / trade-offs

Audit for livelock anywhere multiple actors share retry logic: lock-acquisition retry loops,
message redelivery, network collision handling (the chapter cites Ethernet-style
carrier-sense protocols), and distributed conflict resolution. Jittered exponential backoff
should be the reflexive default for any retry path — it costs a few lines and some added
latency variance. Trade-offs: full jitter maximizes desynchronization but makes latency less
predictable; equal jitter gives a guaranteed minimum delay at the cost of weaker spreading;
priority-based asymmetry breaks ties efficiently but can starve low-priority actors if not
bounded; circuit breakers protect the shared resource but convert delayed success into
immediate failure while open, which callers must be designed to tolerate.

## Fidelity check

1. Claim: thread dumps distinguish livelock from deadlock by thread state. Support: the
   capture's comparison table and detection section say deadlock presents as blocked/waiting
   threads with near-zero CPU while livelock presents as running threads (often at full CPU)
   all executing similar retry logic.
2. Claim: exponential growth alone does not fix synchronized retries. Support: the capture
   notes that pure exponential backoff remains synchronized when threads start together (and
   its delays balloon quickly); only the added randomness breaks the phase lock.
3. Claim: an open circuit breaker rejects operations without attempting them. Support: the
   capture describes the open state as failing all calls immediately so the system gets
   recovery time and retry storms cannot compound the damage.
