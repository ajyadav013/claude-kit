---
source: https://algomaster.io/learn/concurrency-interview/processes-vs-threads
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Choosing between process-level and thread-level concurrency

## What it teaches

The core decision in concurrent design is whether units of work should live in
separate OS processes (own address space, OS-enforced isolation) or as threads
inside one process (shared heap, private stacks). Every downstream property —
crash blast radius, communication cost, memory footprint, scheduling cost,
security posture — falls out of that one choice. The article walks the
trade-off dimension by dimension and lands on the observation that mature
systems rarely pick one exclusively: they layer worker processes for isolation
with threads or event loops inside each worker for cheap concurrency.

## Key patterns & decisions

- **Isolation vs sharing as the axis of choice**: processes get a private
  virtual address space the kernel enforces; threads share code, heap, and file
  descriptors while keeping only a private stack, registers, and thread-local
  storage. Pick processes when a wild-pointer bug in one unit must not be able
  to corrupt another; pick threads when units constantly touch the same
  in-memory state.
- **Creation and context-switch cost gradient**: spawning a process (address
  space, page tables, descriptor duplication) is roughly two orders of
  magnitude slower than spawning a thread (stack plus a small kernel record).
  Likewise a cross-process switch invalidates page-table mappings and cools the
  TLB/caches, while a same-process thread switch keeps them warm — roughly a
  10x difference in switch latency.
- **IPC mechanism selection**: when you do choose processes, match the channel
  to the data shape — pipes/FIFOs for one-way byte streams, kernel message
  queues for framed prioritized messages, shared memory (plus a semaphore) for
  the highest-bandwidth exchange, sockets for anything that might later cross
  machines, files for durable handoff. All of them pay a kernel-boundary tax
  that in-process memory sharing avoids.
- **Fault-isolation architecture**: browsers put each tab in its own process
  and microservices run one process per service precisely so a crash stays
  contained; a segfaulting thread, by contrast, kills every thread in its
  process.
- **Process pool / pre-fork pattern**: pay the expensive process-creation cost
  once at startup, dispatch requests to idle workers, and have the master
  respawn any worker that dies — isolation without per-request spawn cost
  (the nginx/PostgreSQL master-worker shape).
- **Thread pool + work queue inside a process**: reuse a fixed set of threads
  fed by a shared queue rather than spawning per task, avoiding per-task
  creation overhead.
- **Runtime-limit escape hatch**: in runtimes with a global interpreter lock
  (CPython, Ruby), CPU-bound parallelism requires processes regardless of the
  other trade-offs, because threads there cannot execute bytecode in parallel.
- **Threading-model awareness (1:1 / N:1 / M:N)**: mainstream OSes map each
  user thread to a kernel thread (true parallelism, more kernel cost); pure
  user-level threading switches fast but one blocking syscall stalls everything;
  hybrid M:N runtimes (Go's goroutine scheduler) multiplex many light tasks
  onto few kernel threads.

## When to apply / trade-offs

Reach for processes when fault containment, security boundaries (differing
users/privileges, sandboxing untrusted code), cross-machine scaling, or a GIL
force your hand. Reach for threads when tasks share hot in-memory structures,
need sub-microsecond coordination, or must exist in the thousands. The cost of
choosing threads is that the kernel stops protecting you: data races, corrupt
shared state, and whole-process crashes become your problem. The cost of
choosing processes is slower communication, heavier per-unit memory (tens of
MB vs a few MB of stack), and IPC plumbing. Default to the hybrid: process-level
workers for the failure domain, thread/event-loop concurrency within each.

## Fidelity check

1. Claim: process creation is about 100x more expensive than thread creation.
   Support: the capture gives ballpark timings of 1-10 ms to fork a process
   versus 10-100 microseconds to create a thread and explicitly calls the gap
   roughly 100x.
2. Claim: same-process thread switches are cheaper because address-space state
   stays valid. Support: the capture attributes process-switch cost to page
   table swaps and TLB invalidation, quoting ~1-10 us for process switches vs
   ~0.1-1 us for thread switches within a process.
3. Claim: real systems combine both models. Support: the capture's hybrid
   section cites nginx (master + worker processes, event loop per worker),
   PostgreSQL (postmaster spawning per-connection workers), and Chrome
   (browser/GPU/renderer processes, each internally multithreaded).
