---
source: https://blog.algomaster.io/p/concurrency-vs-parallelism
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Concurrency is task interleaving; parallelism is simultaneous execution

## What it teaches

The two words are routinely conflated, but they name orthogonal properties.
Concurrency is a structuring concept: an application makes progress on
several tasks in overlapping time windows, even on a single core, by rapid
switching. Parallelism is a hardware-execution concept: pieces of work
literally run at the same instant on separate cores or accelerators. A system
can have either, both, or neither, and the four-quadrant framing at the end
is the article's most reusable mental model.

## Key patterns & decisions

- **Concurrency = interleaving via context switches**: a single CPU saves one
  task's registers/program counter, loads another's, and flips fast enough to
  create the illusion of simultaneity; the mechanism is threads as the unit of
  schedulable work.
- **Concurrency's goal is utilization, not speed**: while one thread waits on
  I/O, a database call, or an external process, the scheduler hands the core
  to another thread, so the CPU never idles on blocked work.
- **Context switching has a real cost**: every switch spends time saving and
  restoring state, and switch-heavy workloads can lose meaningful throughput
  to that overhead — more interleaving is not free responsiveness.
- **Parallelism = decompose, distribute, execute, aggregate**: split a problem
  into independent subtasks, pin them to distinct cores/GPUs, run them at the
  same wall-clock moment, then merge the partial results (the fork-join
  shape; the article demonstrates it with a divide-until-below-threshold
  array-summing task, described here in prose only).
- **True parallelism needs both threads and cores**: multiple threads on one
  core is still only concurrency; the threads must land on separate physical
  execution units.
- **Four-quadrant taxonomy**: concurrent-not-parallel (single core juggling
  tasks), parallel-not-concurrent (one task fanned across cores, tasks
  themselves strictly sequential, e.g. frame-by-frame rendering), neither
  (pure sequential execution), and both (multi-core systems where some
  subtasks share a core while others run on separate ones).
- **Subtask count follows problem structure, not core count**: it's rarely
  possible to cut work into exactly one piece per CPU, so decomposition
  follows the natural grain of the problem and the scheduler maps pieces onto
  the available cores.
- **Domain mapping**: interactive systems (browsers, web servers, chat, game
  loops) are concurrency stories — staying responsive while juggling
  rendering, input, and I/O; compute pipelines (ML training batches, video
  frames, crawler URL chunks, Spark jobs, scientific simulation) are
  parallelism stories — dividing data to finish sooner.

## When to apply / trade-offs

- Reach for concurrency when the workload is I/O-bound or responsiveness-bound;
  reach for parallelism when it's CPU-bound and decomposable into independent
  pieces. Misdiagnosing which one you need is the classic error the article
  is inoculating against.
- The parallel-not-concurrent quadrant is the least intuitive and worth
  remembering: batch-style pipelines can saturate every core with zero
  task-overlap complexity.
- Interleaved output from concurrent threads (the article shows tasks' steps
  arriving shuffled) is a reminder that ordering guarantees disappear the
  moment work is concurrent.

## Fidelity check

1. *Claim: concurrency's stated objective is maximizing CPU utilization.* The
   capture says the primary objective of concurrency is keeping the CPU
   productive by minimizing idle time, giving the core to another thread
   whenever one blocks on I/O, database transactions, or launching external
   programs.
2. *Claim: the article enumerates four concurrency/parallelism combinations.*
   The capture has a numbered section covering concurrent-not-parallel,
   parallel-not-concurrent (with video rendering of independent frames as the
   example), neither, and both (mixed placement of threads across two cores).
3. *Claim: context switching is presented as a cost, not just a mechanism.*
   The capture has a dedicated cost subsection stating each switch consumes
   time and resources saving/restoring task state and that excessive
   switching degrades performance through added CPU overhead.

Note: the page's two Java code examples (a basic multi-thread demo and a
fork-join array sum) did not survive capture — only their surrounding
explanations and the interleaved-output sample are present. No code was
needed or reproduced for this digest.
