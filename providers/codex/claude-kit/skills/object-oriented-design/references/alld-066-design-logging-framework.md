---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/logging-framework.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Extensible logging framework via pluggable appenders

## What it teaches

This problem is about designing library infrastructure whose primary quality
attribute is extensibility. The shape mirrors real loggers (log4j, logback,
Python's logging): severity levels form an ordered enum, each emitted record
becomes a small value object (timestamp + level + text), and the destination
side is abstracted behind an appender contract so console, file, and database
sinks are interchangeable implementations. New destinations are added by
writing another implementation of the contract — the logger core never
changes. That is the open/closed principle made concrete, and the appender
interface is a Strategy seam between "what to log" and "where it goes."

Configuration is deliberately its own object: the active severity threshold
and the chosen appender live in a config class that can be swapped at
runtime, keeping policy (what gets through, where it lands) separate from
mechanism (formatting and dispatching records). The logger itself is a
singleton offering one convenience method per level, and thread safety is a
stated requirement since many threads log into the same shared sink.

## Key patterns & decisions

- Appender/Strategy seam for outputs: an interface defines how a record is
  written, with console, file, and database implementations — destinations
  are plug-ins, not branches inside the logger.
- Ordered severity enum with threshold filtering: levels from debug through
  fatal are an enumeration, and the configured minimum level decides which
  records pass.
- Log record as a value object: every message is captured as an object
  bundling timestamp, level, and content, giving appenders a uniform unit to
  serialize however they like.
- Config object separated from logger: threshold and destination live in a
  dedicated configuration class, so behavior changes are a config swap rather
  than a logger rewrite, including at runtime.
- Singleton logger with per-level convenience API: one shared entry point,
  with a shorthand method for each severity so call sites stay terse.
- Thread safety as a core requirement: the framework must accept concurrent
  emissions from many threads, pushing synchronization into the shared
  logging path rather than onto callers.
- Extensibility promise in both dimensions: the design explicitly anticipates
  future new levels and new destinations without core modification.

## When to apply / trade-offs

- The appender seam generalizes to any fan-out infrastructure: metrics
  exporters, notification channels, audit sinks — whenever "produce an event"
  and "deliver an event" should evolve independently.
- A singleton logger is ergonomic (log from anywhere) but injects a hidden
  global; testing and multi-tenant scenarios favor injected logger instances
  even at some call-site verbosity cost.
- Holding a single active appender in config is simpler than the multi-
  appender lists real frameworks use; if records must go to several sinks at
  once, the config needs a collection and the dispatch loop changes shape.
- Synchronizing the shared path is correct but can make logging a contention
  point under load; production-grade designs move to async queues/buffered
  appenders, trading immediacy and possible loss-on-crash for throughput.
- A database appender couples logging to another failable service — the
  design should decide whether sink failure may ever break the caller.

## Fidelity check

1. Claim: output destinations are abstracted behind one contract with three
   provided implementations. Support: the capture defines an appender
   interface plus console, file, and database implementations of it.
2. Claim: configuration (threshold + destination) is a separate object from
   the logger. Support: the capture describes a dedicated config class holding
   the log level and selected appender, which the singleton logger accepts.
3. Claim: concurrent use is an explicit design requirement, not incidental.
   Support: the capture's requirements demand thread safety for logging from
   multiple threads, and its demo description includes logging from several
   threads with runtime configuration changes.
