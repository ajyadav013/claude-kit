---
source: https://algomaster.io/learn/lld/singleton
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Singleton: the one-instance guarantee, its thread-safety ladder, and why to reach for DI first

## What it teaches

The creational pattern that restricts a class to a single shared instance with
a global access point. The chapter's real substance is the *implementation
ladder*: it starts from the naive lazy version that breaks under concurrency
and climbs step by step — coarse locking, double-checked locking, eager
creation at load time, and finally the language-level idioms (class-loader
tricks and enum-backed singletons in Java) that get the runtime to do the
synchronization for you. It closes with an honest cons list: singletons are
global state in disguise, and dependency injection is usually the better
default.

## Key patterns & decisions

- **Restrict construction, expose one accessor.** The design is three parts: a
  hidden/private constructor so outside code cannot instantiate, a class-level
  field holding the sole instance, and an accessor method that creates it on
  demand and thereafter always returns the same object.
- **Naive lazy init is a race.** Checking "is the field empty?" then creating
  is not atomic; two threads arriving together can each pass the check and
  build separate instances. This version is only safe single-threaded.
- **Full-method locking: correct but slow.** Guarding the entire accessor with
  a lock fixes the race, but every read after the first still pays for lock
  acquisition it no longer needs.
- **Double-checked locking.** Check without the lock; only if the field looks
  empty, take the lock and check again before constructing. Amortizes to
  lock-free reads once initialized, at the cost of subtler code.
- **Eager initialization.** Build the instance during class/module load —
  inherently thread-safe because runtimes initialize static state exactly once,
  but wasteful if the object is heavy and might never be used.
- **Lean on the runtime's initialization guarantees.** The holder-class idiom
  defers creation until first access by exploiting the fact that a nested class
  is loaded only when referenced, and class initialization is specified to be
  thread-safe — lazy, fast, and lock-free without hand-rolled synchronization.
- **Enum singleton as the strongest guarantee (Java).** An enum constant is
  initialized once, survives serialization round-trips as the same instance,
  and cannot be duplicated via reflection — protections no hand-written variant
  gets. Limitation: an enum cannot extend another class.
- **Prefer dependency injection over global access.** Because singletons hide
  dependencies, couple callers to a concrete class, and make tests share state,
  the chapter's closing advice is to reach for DI where possible and use the
  pattern only for genuinely process-wide resources (connection pools, loggers,
  caches, config).

## When to apply / trade-offs

- Legitimate uses are resources that must be exactly-once per process: pools,
  spoolers, shared in-memory caches, logging sinks, configuration.
- The worked example is a shared cache manager: one instance means one map, so
  writes from any component are instantly visible everywhere, TTL expiry lives
  in one place, and nothing has to thread a cache reference through every
  constructor.
- Costs: the pattern mixes two responsibilities (lifecycle control plus the
  business role), introduces global state that unit tests cannot easily isolate
  or mock, and tightly couples every consumer to the concrete class.
- A singleton beats a bare global variable because it controls *when* and *how*
  initialization happens (laziness, thread safety, validation), not just
  visibility.

## Fidelity check

1. *Claim:* the naive lazy accessor can yield two instances under concurrency.
   *Capture support:* the chapter explicitly flags the lazy version as not
   thread-safe because simultaneous calls while the field is still null can
   each construct an object.
2. *Claim:* double-checked locking exists to avoid paying lock cost after
   initialization. *Capture support:* the capture motivates it as fixing the
   synchronized version's flaw that every call locks even once the instance
   exists, restricting synchronization to first creation only.
3. *Claim:* the enum approach gives serialization and reflection immunity that
   other variants lack. *Capture support:* the capture enumerates four JVM-level
   guarantees for enum singletons — once-only thread-safe init, deserialization
   returning the same instance, reflection-based construction being rejected,
   and instance uniqueness enforced by the VM — noting the no-superclass
   restriction as the only drawback.
