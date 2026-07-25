---
source: https://algomaster.io/learn/concurrency-interview/race-conditions-and-critical-sections
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Race conditions: the three ingredients and the critical-section cure

## What it teaches

A race condition is a correctness bug where the outcome depends on which
thread's operations land first. Its defining danger is silence: nothing
crashes, no exception fires, the data is just quietly wrong, and the wrongness
varies run to run because it depends on scheduler timing you can't reproduce
in tests. The article decomposes races into three necessary ingredients,
names the two canonical shapes (read-modify-write and check-then-act), and
frames the fix as protecting critical sections so that shared-state updates
become atomic from every other thread's point of view.

## Key patterns & decisions

- **Three-ingredient test for races**: shared state + at least one writer +
  unsynchronized concurrent access. Removing any single ingredient eliminates
  the race, which yields three whole families of fixes — don't share, don't
  mutate, or synchronize.
- **Read-modify-write races**: an increment that looks like one statement is
  really load, add, store at machine level; another thread can interleave
  between any pair of steps, so two concurrent increments can collapse into
  one (a lost update).
- **Check-then-act races**: verifying a condition and then acting on it are
  separate steps, and the condition can change in between — the lazy-singleton
  double-construction bug and inventory overselling (two buyers both see one
  unit in stock, both decrement) are the same defect shape.
- **Races generalize beyond memory**: the same lost-update and check-then-act
  shapes appear at the database and payments layer — two editors overwriting
  each other's saved record, or two rapid payment submissions both passing the
  balance check and double-debiting. The critical-section discipline applies
  to rows and accounts, not just heap variables.
- **Critical section definition and the four correctness properties**: a
  region touching shared state should guarantee mutual exclusion (one thread
  inside at a time), progress (an empty section admits a waiter), bounded
  waiting (no starvation), and independence from relative thread speeds.
- **Three protection mechanisms, escalating in generality**: hardware atomic
  operations for single counters/flags (lock-free), a mutex for arbitrary
  multi-step sections, and immutability to delete the race by deleting
  mutation.
- **Non-determinism as the testing implication**: because races surface only
  under particular interleavings, a passing test suite proves little;
  prevention by construction (one of the three fixes) beats detection by
  testing.

## When to apply / trade-offs

Apply the three-ingredient test during design review of any code that multiple
threads, requests, or jobs can reach: enumerate the shared mutable things and
ask what guards each. Prefer the cheapest sufficient fix — immutable or
thread-confined data needs no locking and no reasoning; an atomic covers a
single-word update; a mutex covers compound invariants but introduces
contention and (with multiple locks) deadlock-ordering concerns. The
check-then-act shape deserves special vigilance because it hides in innocent
"if absent then create" and "if funds then debit" logic, and it cannot be
fixed by making the individual reads and writes atomic — the check and the act
must be fused inside one protected region.

## Fidelity check

1. Claim: races corrupt silently and non-deterministically. Support: the
   capture opens with a two-thread counter experiment whose expected total of
   2,000 comes out as a different wrong number on every run, and stresses that
   no exception or crash accompanies the corruption.
2. Claim: an increment is three machine steps, not one. Support: the capture
   breaks the increment into loading the value into a register, adding one,
   and storing back, and names interleaving between these steps the
   read-modify-write race; its diagram shows both threads reading zero and
   both writing one, losing an update.
3. Claim: removing any one of the three ingredients removes the race.
   Support: the capture lists shared state, mutability, and unsynchronized
   concurrent access as the required trio and explicitly notes immutable data,
   unshared data, and properly synchronized access are each individually
   race-free.
