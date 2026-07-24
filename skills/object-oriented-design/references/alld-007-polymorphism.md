---
source: https://algomaster.io/learn/lld/polymorphism
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Polymorphism: one call site, many behaviors, chosen by the receiver

## What it teaches

Polymorphism lets a single method name or interface produce different
behavior depending on which concrete object receives the call. Code targets
a common type; the actual behavior is supplied by whatever implementation
sits behind it. The chapter's analogy is a universal remote: the buttons
never change, but a TV, an air conditioner, and a projector each interpret
the same signal in their own way — a stable interface over divergent
receivers.

Four benefits are claimed: loose coupling (callers touch abstractions, not
concrete classes), flexibility (new behaviors arrive without editing
existing code, i.e., open/closed), scalability (feature growth with minimal
blast radius), and extensibility (new implementations plug into unchanged
core logic).

The mechanics split into two forms with fundamentally different resolution
points:

1. Compile-time (overloading): several same-named methods in one class,
   distinguished by parameter count/types/order. The compiler picks the
   variant from the arguments at the call site before the program ever
   runs — no runtime decision exists.
2. Runtime (overriding / dynamic dispatch): a child class replaces a
   parent-declared method, and the version invoked is chosen at runtime
   from the object's *actual* type, not the reference's *declared* type.
   The chapter calls this the more powerful and important form. Its
   notification example makes the distinction concrete: a collection is
   typed to the base notification, yet iterating and invoking send executes
   the email, SMS, or push variant per element — the variable says base
   type, the behavior says concrete type.

The chapter then addresses the interface-vs-abstract-class choice for
enabling polymorphism, since dispatch works identically through either. The
decision table it builds: interfaces model a capability ("can do") that
structurally unrelated classes share, carry no shared behavior, and can be
implemented many at a time; abstract classes model a family ("is a") with
shared fields and concrete methods, but a class extends only one. Its
examples: a sendable capability implemented by email, invoice, and report
classes that share nothing structurally, versus a notification family whose
members share formatting, fields, and constructor shape. The closing advice
is that mature designs often combine both — an abstract family base for
shared logic plus a thin capability interface for cross-family contracts.

## Key patterns & decisions

- Program to the base type, dispatch on the concrete type: collections and
  parameters typed to the abstraction, behavior resolved per element at
  runtime.
- Overloading vs overriding split: compile-time argument-based selection vs
  runtime receiver-based selection — different mechanisms, same surface
  spelling.
- Dynamic dispatch as the extension mechanism: new variants extend behavior
  without touching call sites (open/closed).
- Capability-vs-family test for the abstraction vehicle: interface for a
  shared "can do" across unrelated types; abstract class for a shared "is a"
  with common logic.
- Combine both layers: abstract base for intra-family reuse plus a small
  interface for cross-family contracts.
- Declared-type vs actual-type distinction: the reference type constrains
  what you may call; the object type decides what actually runs.

## When to apply / trade-offs

Runtime polymorphism is the tool whenever call sites would otherwise switch
on a type tag, and it is the payoff that justifies inheritance or interface
hierarchies at all. Overloading is a lighter convenience — same-name
ergonomics with zero runtime cost but also zero extensibility. Choosing an
abstract class buys shared logic at the price of the single-parent slot;
choosing an interface preserves multiple-implementation freedom at the price
of duplicating any common behavior. The chapter's implicit caution: since
dispatch follows the actual type, every override must honor the base
contract, or base-typed callers break.

## Fidelity check

1. Claim: the two forms differ in when the dispatch decision is made.
   Support: the capture states overloading is resolved by the compiler from
   the argument list before the program runs, while overriding is resolved
   at runtime from the actual object type rather than the declared
   reference type.
2. Claim: the notification example demonstrates base-typed storage with
   concrete-typed behavior. Support: it describes a list whose every
   element is held as a base notification reference, yet the runtime
   invokes each child class's own send implementation.
3. Claim: the chapter recommends interfaces for capabilities across
   unrelated classes and abstract classes for families with shared logic,
   often together. Support: its comparison table maps interfaces to "can
   do" with no shared behavior and many-implementable, abstract classes to
   "is a" with concrete methods and single extension, and it closes by
   noting many designs use an abstract family base plus a capability
   interface simultaneously.
