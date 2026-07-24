---
source: https://algomaster.io/learn/lld/dependency
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Dependency: the transient "uses-a" relationship and why it enables DI

## What it teaches

This chapter covers the weakest link two classes can have: one class briefly
uses another to get a job done and then forgets about it. Unlike
association, aggregation, or composition, there is no stored field, no shared
lifecycle, and no lasting structural bond — the collaboration lives only for
the duration of a single method call. UML renders this lightness as a dashed
arrow from the user to the used class.

The chapter teaches you to recognize dependency in four concrete code shapes:
a collaborator arriving as a method parameter, a helper instantiated as a
local variable inside a method, a type appearing only as a return value (the
factory case), and a purely class-level reliance through static utility
calls. The dividing line with association is precise: the instant a class
stores the collaborator in an instance field, the temporary dependency
hardens into a persistent association.

The second half pivots to dependency injection. When a class needs
collaborators to work, it can either construct them internally — welding
itself to one concrete implementation — or declare what it needs and let the
outside world supply it. The chapter walks a notification service through
this refactor: hard-wiring an email sender inside the service makes it
impossible to switch channels, impossible to unit-test without real side
effects, and forces edits to existing code for every new channel. Injecting
an abstract sender through the constructor fixes all three at once. A closing
worked example shows a ticket-booking coordinator that receives a seat
validator, payment processor, QR generator, and email service purely as
method parameters — zero fields, four dashed arrows, every collaborator
mockable independently.

## Key patterns & decisions

- **Dependency as method-scoped collaboration**: the relationship exists only
  while a method executes; no instance field, no ownership, no lifecycle
  management — the lightest coupling available between classes.
- **Field-storage as the association threshold**: caching a collaborator in
  an instance variable converts a dependency into an association; keeping it
  parameter-scoped keeps the class structurally free of it.
- **Four recognizable dependency forms**: method parameter, method-local
  instantiation, return type (factories), and static utility call — a
  checklist for spotting hidden coupling in code review.
- **Dependency injection over internal construction**: classes should receive
  their collaborators from outside rather than new-ing them up, so
  implementations can be swapped without touching the consumer.
- **Depend on abstractions, not concretions**: injecting an interface (a
  generic sender) instead of a concrete class (an email sender) is what makes
  swapping and mocking possible; frameworks like Spring, ASP.NET, and NestJS
  automate the wiring but the principle is framework-free.
- **Test seams via injected mocks**: because collaborators come in from
  outside, unit tests can substitute recorders/fakes and verify behavior
  (e.g., simulate a failed payment) with no real side effects.
- **Coordinator with zero fields**: an orchestration class that takes every
  collaborator as a call-time parameter maximizes single-responsibility
  separation — each helper does one thing, the coordinator only sequences
  them.

## When to apply / trade-offs

Prefer dependency over association whenever the collaboration is genuinely
momentary — pass the collaborator in, use it, let it go. This keeps classes
easy to reason about and test, but pushes the wiring burden outward: someone
(a caller, a factory, or a DI container) must assemble the object graph.
Internal construction is only defensible for trivial, side-effect-free
helpers; anything touching I/O, external services, or configuration should be
injected behind an abstraction. The Open/Closed argument seals it: adding a
new implementation should mean writing a new class, never editing the
consumer.

## Fidelity check

1. *Claim: storing the collaborator as a field upgrades the relationship to
   association.* The capture makes exactly this point with the printer
   example — if the printer kept a reference to the last-printed document in
   a private field, the structural link would outlive the method call and the
   relationship would no longer be a mere dependency.
2. *Claim: the chapter enumerates four code forms of dependency.* The capture
   has a dedicated section listing method parameters, local variables, return
   types, and static method calls, each with its own mini-scenario (report
   generator, order processor, user factory, password service).
3. *Claim: internal construction of an email sender breaks testability and
   Open/Closed.* The capture lists three concrete problems with the hard-wired
   version of the notification service: implementations cannot be switched
   without modifying the class, unit tests would trigger real email sends, and
   adding a channel requires changing existing code rather than extending it.
