---
source: https://algomaster.io/learn/lld/abstraction
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Abstraction: three mechanisms for separating what from how

## What it teaches

Abstraction means presenting a simplified, essential view of a component
while suppressing the machinery underneath — callers program against what a
thing does, never how. The chapter's motivating anti-example is a logging
service that internally branches per destination (console, file, remote):
every new destination adds a branch, the service is coupled to every
mechanism, and testing or changing one path risks the others.

Introducing an abstract logger type dissolves this. The chapter enumerates
four concrete payoffs: implementations become swappable at the single
construction site while all consuming code is untouched; consumers are
shielded from file handles, network connections, and buffering; new
destinations arrive as new subclasses with zero edits to existing classes
(open/closed in action); and cross-cutting logic like timestamp-and-level
message formatting is written once in the base type instead of duplicated
per branch.

Its most useful contribution is naming three distinct mechanisms and when
each fits:

1. Abstract classes — a blueprint for a *family* of related types, mixing
   unimplemented operations (each subclass must supply) with fully
   implemented shared ones (each subclass inherits). Their differentiator
   over interfaces: they share behavior, not just a contract.
2. Interfaces — a *capability* shared across structurally unrelated types.
   The example is an export capability implemented by CSV, JSON, and XML
   exporters that have nothing else in common; the interface is pure
   contract, no shared logic.
3. A clean public API on an ordinary class — no inheritance needed. A
   database client exposing only connect/query while privately managing
   pooling, sockets, auth handshakes, and retries is abstraction by surface
   design alone.

The chapter also sharply separates abstraction from encapsulation:
abstraction is the external, design-level simplification (the accelerator
pedal); encapsulation is the internal, implementation-level protection of
state (the sealed engine). One simplifies, the other protects.

A closing media-player design shows the pattern end to end: an abstract
player declares play/pause/stop as subclass responsibilities while providing
shared status-display and action-logging methods; a controller depends only
on the abstract type, so audio, video, streaming — or any future — player
plugs in without controller changes, and each player keeps its own
complexity (buffering, resolution) to itself.

## Key patterns & decisions

- Depend on an abstract type at the consumption site; choose the concrete
  type at a single construction point.
- Abstract class for families with shared logic; interface for capabilities
  across unrelated types; plain public API when no hierarchy is needed.
- Template-style division of labor: base type owns invariant behavior
  (formatting, logging), subclasses own only what genuinely varies.
- Open/closed extension: new variants are new subclasses/implementations,
  never edits to existing consumers.
- Abstraction vs encapsulation split: external simplification vs internal
  state protection — related but independently applicable.
- Conditional-dispatch smell: per-variant if/else branches inside one class
  signal a missing abstraction.

## When to apply / trade-offs

Reach for abstraction when a consumer would otherwise branch on variant
types, when implementations must be swappable (testing doubles included), or
when common logic is being duplicated across variants. The mechanism choice
is the real decision: abstract classes buy shared behavior at the cost of
single inheritance and tighter family coupling; interfaces stay maximally
loose but cannot host common logic; a plain well-surfaced class is the
cheapest option when there is only one implementation. Over-abstracting a
single-implementation path adds indirection with no payoff — the chapter's
own third mechanism is the reminder that a small public API is often enough.

## Fidelity check

1. Claim: the motivating anti-example is a logging service coupled to every
   destination via internal branching. Support: the capture describes a
   LoggingService that directly creates and manages each logger type, where
   every new destination means another branch and changing one mechanism
   risks breaking others.
2. Claim: the chapter distinguishes abstract classes (shared behavior) from
   interfaces (contract only) as different abstraction tools. Support: it
   states abstract classes let a family share concrete methods like a common
   message formatter, while the export interface example shares no behavior
   at all — purely a contract that unrelated exporters satisfy.
3. Claim: abstraction can be achieved without inheritance via a clean public
   API. Support: the capture's database-client example exposes just connect
   and query while pooling, socket lifecycle, authentication, and retry
   logic stay private, and explicitly calls the public API itself the
   abstraction.
