---
source: https://algomaster.io/learn/lld/inheritance
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Inheritance: is-a hierarchies, their shapes, and when composition wins

## What it teaches

Inheritance lets a child class absorb the fields and behavior of a parent
and then specialize: override what must differ, add what is new. The chapter
grounds it in a user-roles design — a base user type owns credentials and
login/logout behavior, while admin, customer, and vendor types layer
role-specific behavior on top of that shared core.

The claimed benefits are reuse (shared logic lives once, honoring DRY), an
intuitive hierarchy that mirrors real "is-a" relationships, single-point
maintenance (a fix in the parent propagates to every child), and being the
enabling mechanism for runtime polymorphism.

A taxonomy of hierarchy shapes follows, each with a judgment attached:

- Single inheritance (one child, one parent) — the universal, safest form.
- Multi-level (child becomes a parent in turn) — acceptable shallow, but
  chains of five-plus levels are called out as fragile and hard to reason
  about.
- Hierarchical (many children under one parent) — extremely common and
  natural.
- Multiple inheritance (one child, several parents) — the troublesome one,
  because of the diamond problem: when two parents define the same
  operation, which does the child invoke? Languages resolve this
  differently: C++ offers virtual inheritance (described as complex and
  error-prone), Python defines a deterministic method resolution order via
  C3 linearization, and Java/C#/TypeScript sidestep it entirely — one class
  parent only, but many interfaces.

The chapter's most transferable content is its use/avoid checklist. Use
inheritance only when a genuine "is-a" sentence reads naturally, the parent
holds behavior all children truly share, a child never breaks expectations a
parent-typed reference carries (a substitutability requirement), and the
hierarchy stays two to three levels. Avoid it when the relationship is
"has-a"/"uses-a" (a car has an engine; a printer uses a logger), when
behaviors must combine or swap at runtime (inheritance fixes the parent at
compile time; composition injects and swaps freely), or when parent-child
coupling would let parent changes ripple through a large tree. The default
guidance: when unsure, start with composition — refactoring toward
inheritance later is far easier than untangling a deep tree back into
composition.

A notification-system example closes the loop: a base notification type owns
recipient, message, timestamp, and a shared header-formatting method; email,
SMS, and push children each own their channel quirks (subject line,
character cap, device token and priority) without leaking them upward or
sideways, and a new channel is one new subclass with zero edits elsewhere.

## Key patterns & decisions

- Is-a test as the gate: if "X is a Y" reads unnaturally, use composition
  instead.
- Shallow-hierarchy budget: two to three levels; deep chains are a design
  smell.
- Diamond-problem awareness: know your language's stance (virtual
  inheritance, MRO/C3, or single-class-plus-interfaces) before reaching for
  multiple inheritance.
- Substitutability requirement: a child must honor every behavioral
  expectation of a parent-typed reference (Liskov in all but name).
- Composition-first default: prefer has-a wiring when in doubt; it preserves
  runtime swap/mix flexibility that inheritance forecloses.
- Channel-quirk containment: variant-specific constraints live in the
  variant subclass, never in the parent or siblings.
- Single-point shared logic: cross-variant behavior (e.g., header/timestamp
  formatting) lives once in the base.

## When to apply / trade-offs

Inheritance pays off for genuine families with stable shared behavior and a
shallow tree; it costs you compile-time lock-in to one parent, tight
coupling to parent internals, and ripple risk on parent changes. Composition
costs a little wiring but keeps behaviors swappable and independently
testable. The asymmetry of refactoring effort (composition→inheritance easy,
inheritance→composition hard) is the practical reason to default to
composition.

## Fidelity check

1. Claim: the chapter caps healthy hierarchies at roughly 2–3 levels and
   flags deep chains. Support: the multi-level section says chains of five
   or more levels become fragile and hard to understand, and the use-when
   checklist names shallow hierarchies of two to three levels.
2. Claim: languages resolve the diamond problem in three distinct ways.
   Support: the capture states C++ uses virtual inheritance (complex,
   error-prone), Python uses a method resolution order based on C3
   linearization, and Java/C# avoid it by allowing one class parent with
   multiple interfaces.
3. Claim: the chapter's default is composition when in doubt, citing
   refactoring asymmetry. Support: it advises starting with composition
   because moving to inheritance later is easy, while untangling a deep
   inheritance tree into composition is much harder.
