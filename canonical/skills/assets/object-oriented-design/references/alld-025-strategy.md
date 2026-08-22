---
source: https://algomaster.io/learn/lld/strategy
author: algomaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Strategy: swap the algorithm, keep the caller

## What it teaches

How to take one operation that can be performed several different ways —
computing shipping cost by flat rate, by weight, by distance zone, by express
tier, or by calling a carrier's API — and structure it so each variant lives in
its own class behind a shared interface. The chapter's starting point is a
calculator class that selects a variant via a growing conditional chain keyed
on a string. That version works until the business adds methods: each addition
reopens a supposedly stable class, the branch logic bloats, individual
algorithms can't be unit-tested without staging the whole calculator, and other
parts of the app that need the same math are tempted to copy the block. The
pattern's core move is separating what varies (the algorithm) from what stays
the same (the orchestration), with the context holding a reference typed to the
strategy interface and delegating blindly.

## Key patterns & decisions

- **One class per algorithm variant**: each pricing scheme is isolated with its
  own data and logic; the weight-based one knows nothing about zones and vice
  versa.
- **Context delegates through an interface**: the service stores a strategy
  reference and forwards the call; it never learns which concrete variant is
  installed.
- **Runtime swappability**: strategies are injected via constructor or setter
  and can be replaced mid-flow (the chapter's example: a shopper upgrading from
  standard to express during checkout) with zero context changes.
- **Type-safe dispatch over string dispatch**: replacing string-keyed branch
  selection with real objects moves mistakes from runtime to compile time.
- **Interface vs abstract base decision rule**: the chapter chooses a bare
  interface because the variants share no implementation, and notes that shared
  scaffolding (e.g., common logging around the computation) would justify an
  abstract class with a template method instead.
- **Testability in isolation**: each variant can be exercised directly with a
  small input, rather than steering a monolithic method into a specific branch.
- **Open/Closed for new variants**: a new scheme (the chapter suggests free
  shipping for premium members) is one new class; the service and existing
  variants are untouched.
- **Composition over inheritance**: behavior is assembled by plugging objects
  together, not by subclassing the calculator.

## When to apply / trade-offs

Reach for it when there are multiple interchangeable ways to do one job and the
choice may vary by client, configuration, or moment in time — the chapter
reinforces this with a second domain, payment processing, where a checkout
service charges via card, wallet, or cryptocurrency through the identical
plug-in shape. It also frames a lo-fi analogy (choosing among car, taxi,
transit, or shuttle to reach the airport: the goal is fixed, the method swaps).
Costs: more classes and a small indirection layer, and the client must know
enough to pick or be handed a strategy. If there are only two stable variants
and no runtime switching, a simple conditional may be the honest answer;
Strategy earns its keep once the variant set is open-ended or the branch logic
starts duplicating.

## Fidelity check

1. Claim: the pre-pattern version selects behavior with fragile string-based
   dispatch. Support: the capture describes the client passing a method name
   into the calculator and later lists "no string-based dispatch" as a gain,
   noting the compiler now catches mistakes.
2. Claim: strategies can be exchanged even mid-execution without touching the
   context. Support: the capture's workflow states the context holds an
   interface-typed reference and that swapping in a different strategy changes
   behavior with no context-code modification, illustrated by a user upgrading
   shipping tier during checkout.
3. Claim: the chapter gives an explicit criterion for interface versus abstract
   class. Support: its design-decision aside says an interface was chosen
   because the shipping variants share no implementation, and that shared
   pre-work such as logging would instead warrant an abstract class with a
   template method.
