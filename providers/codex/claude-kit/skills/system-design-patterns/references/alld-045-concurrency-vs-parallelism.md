---
source: https://algomaster.io/learn/concurrency-interview/concurrency-vs-parallelism
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Concurrency is program structure; parallelism is simultaneous execution

## What it teaches

This chapter draws the line between two chronically conflated ideas.
Concurrency is a property of how a program is organized: it is designed so
several tasks can be in flight over overlapping periods. Parallelism is a
property of what happens at runtime: multiple tasks literally executing at
the same instant on separate cores. The asymmetry matters — a concurrent
program can run on one core (interleaved, never simultaneous), but a program
cannot execute in parallel unless it was first structured concurrently,
because parallel execution needs independent tasks to hand out. The chapter
anchors this in Rob Pike's formulation that concurrency is about dealing with
many things at once while parallelism is about doing many things at once.

A kitchen analogy maps the four quadrants: one cook finishing dishes strictly
one after another (neither), one cook rotating between dishes while things
simmer (concurrent, not parallel), several cooks each on one dish
(parallel, which presupposes concurrent structure), and several cooks each
juggling several dishes (both — explicitly likened to a modern web server
with multiple threads each multiplexing many connections). A truth table
formalizes it, with the concurrent-no/parallel-yes cell marked impossible.

Real workloads then illustrate which property earns the win. An I/O-dominated
web server gets most of its capacity from concurrency alone — a
single-threaded async server can hold thousands of connections by overlapping
waits — with parallelism mainly helping CPU-heavy phases and fault isolation.
Video encoding is the opposite: CPU-bound per frame, so concurrency without
extra cores buys little and parallel frame encoding is the lever. GUI apps
need concurrency for responsiveness above all; MapReduce needs both, with
data partitioning supplying the concurrent structure that cluster-wide
parallel execution then exploits.

Five misconceptions get dismantled: concurrent does not imply parallel; more
threads do not always help (past core count, CPU-bound work just pays
context-switch overhead, and I/O gains taper); async/await is non-blocking
concurrency, not parallelism (a single-threaded event loop is highly
concurrent but not parallel); multiple cores are not required for concurrency
(time-sharing predates multicore by decades); and parallel is not always
faster (thread management, synchronization, cache-coherency traffic, and
Amdahl's Law can make sequential the fastest option for small tasks). A
levels-of-parallelism table (bit, instruction, SIMD data, task, distributed)
notes CPUs already parallelize internally, which further dilutes the
returns from piling on threads.

The chapter closes with four design principles for concurrency-friendly
programs: decompose into independent tasks, minimize shared mutable state
(every synchronization point serializes execution), pick task granularity
that balances scheduling overhead against distribution (its example: a
million items is better as a thousand tasks of a thousand items than either
extreme), and match strategy to workload type — async concurrency for
I/O-bound, core-count parallelism for CPU-bound, and phase-splitting for
mixed loads.

## Key patterns & decisions

- **Structure/execution split**: treat concurrency as a design-time property
  of the program and parallelism as a runtime property of the hardware and
  scheduler; the former is necessary but not sufficient for the latter.
- **Workload-first strategy selection**: I/O-bound work is won by overlapping
  waits (async, single core suffices); CPU-bound work is won by scaling
  threads to core count; mixed work should be split into phases optimized
  separately.
- **Single-threaded event loop as high-concurrency baseline**: an async
  server on one thread can multiplex thousands of connections — parallelism
  is an additive optimization for compute-heavy parts, not the source of I/O
  capacity.
- **Thread-count restraint**: beyond core count for CPU-bound work, extra
  threads convert useful time into context-switching and coordination
  overhead; I/O gains from added threads diminish and vanish.
- **Shared-state minimization for scalability**: worker-local state merged at
  the end beats continuously updated shared structures, because each
  synchronization point is a serialization bottleneck.
- **Granularity tuning**: task size must sit between overhead-dominated
  (too fine) and undistributable (too coarse); batching items into
  moderately sized chunks is the usual sweet spot.
- **Parallelism-overhead skepticism (Amdahl framing)**: thread lifecycle,
  synchronization, and cache-coherency costs mean small tasks can run fastest
  sequentially; measure before parallelizing.
- **Layered parallelism awareness**: bit-, instruction-, and SIMD-level
  parallelism inside the CPU already run concurrently with your code, which
  is one reason thread-level speedups fall short of linear.

## When to apply / trade-offs

Use this distinction whenever choosing an execution model: profile whether
the workload waits or computes before reaching for threads. Async
single-threaded designs maximize simplicity and I/O concurrency but leave
cores idle for compute; multi-threaded parallelism buys compute speed at the
price of synchronization complexity and diminishing returns past core count.
The design principles (independent tasks, minimal sharing, right-sized
chunks) are what keep the door open to parallel execution later — a program
without concurrent structure cannot be parallelized no matter how many cores
arrive.

## Fidelity check

1. *Claim: parallelism without concurrency is impossible.* The capture's
   relationship table marks the not-concurrent-but-parallel combination as
   impossible and explains that parallel execution requires multiple
   independent tasks, which only a concurrent structure provides.
2. *Claim: async/await is presented as non-blocking concurrency rather than
   parallelism.* The capture's third misconception states that a
   single-threaded event loop such as Node.js is highly concurrent by
   overlapping waits but not parallel unless work moves to more threads or
   processes.
3. *Claim: the granularity guidance uses a million-item example with a
   thousand-by-thousand split as the balanced choice.* The capture contrasts
   one million single-item tasks (overhead dominates) and one monolithic task
   (no parallelism) against a thousand tasks of a thousand items as the
   usually-better balance.
