---
source: https://algomaster.io/learn/concurrency-interview/deadlock
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Deadlock: the four Coffman preconditions and how each prevention strategy breaks one

## What it teaches

Deadlock is a permanent standstill in which a group of threads each holds a resource and
waits on a resource held by another member of the same group, forming a cycle that can never
resolve on its own. Its danger is its silence: no exception, no crash, just a system that
stops progressing — like two cars meeting mid-span on a one-lane bridge with traffic packed
in behind both. The chapter's central framework is Coffman's 1971 result: four conditions
(mutual exclusion, hold-and-wait, no preemption, circular wait) must all hold at once for
deadlock to exist, so every prevention technique can be understood as a deliberate attack on
exactly one of them. It also covers why deadlocks hide during development and how to find
them in a running system.

## Key patterns & decisions

- **Coffman's four-condition model as a design checklist**: exclusive resources, holding
  while waiting, no forcible reclamation, and a wait-for cycle must coexist; negate any one
  and deadlock becomes impossible.
- **Break mutual exclusion with shareable designs**: reader-writer locks let readers coexist,
  and immutable data removes the need for locking entirely.
- **Break hold-and-wait with all-or-nothing acquisition**: grab every lock a task needs up
  front, and if the full set is unavailable, release everything and start over.
- **Break no-preemption with deadline-bearing acquisition**: a timed try-lock that gives up,
  releases held locks, and backs off is a self-imposed form of preemption.
- **Break circular wait with total lock ordering (the workhorse strategy)**: assign every lock
  a global rank and acquire strictly in ascending order — e.g. order account locks by ID in a
  transfer, so any pair of transfers, in either direction, takes the locks the same way and no
  cycle can form.
- **Recognize the recurring deadlock breeding grounds**: divergent lock order between two code
  paths; nested locking across module boundaries where neither team knows the other's locks;
  invoking user callbacks while holding a lock; and database transactions updating the same
  rows in opposite orders.
- **Deadlocks are timing bugs that evade testing**: they need a particular interleaving,
  single-threaded tests never hit them, added logging perturbs timing enough to mask them,
  and they typically first surface under production load.
- **Detect via thread dumps, wait-for graphs, and periodic programmatic checks**: dumps show
  who holds and awaits what (some runtimes explicitly name the deadlocked threads); a
  resource-allocation graph with holds and wants as edges reveals deadlock as a cycle; a
  monitoring thread can poll for deadlocked-thread sets and alert before users notice.

## When to apply / trade-offs

Lock ordering is the default choice when you control all acquisition sites: it is cheap and
deterministic, but it requires a discoverable global order and discipline across the whole
codebase, which erodes when third-party code takes locks you cannot see. Timed try-lock plus
release-and-retry works without global coordination but trades determinism for retry loops
and backoff tuning. All-or-nothing acquisition is simple to reason about but can hurt
throughput by over-holding locks and can starve tasks needing large lock sets. The
cross-module and callback cases argue for a broader design rule: avoid calling foreign or
user-supplied code while holding a lock. Database work needs the same thinking — touch rows
in a consistent order inside transactions.

## Fidelity check

1. Claim: all four conditions must hold simultaneously, so removing one suffices. Support:
   the capture attributes to Coffman (1971) the identification of four conditions that must
   ALL be present, and organizes its whole prevention section as one breaking technique per
   condition.
2. Claim: ordering locks by a stable key makes transfer-style deadlocks impossible. Support:
   the capture's ordering strategy notes that whichever two accounts are involved, the lower-
   ranked lock is always taken first, so a wait-cycle between two transfer threads cannot
   arise.
3. Claim: some runtimes can identify a deadlock for you in a thread dump. Support: the
   capture states that the JVM's dump output explicitly detects the deadlock and reports
   which threads participate and where they are stuck.
