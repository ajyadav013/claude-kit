---
source: https://algomaster.io/learn/lld/factory-method
author: algomaster.io (AlgoMaster)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Factory Method: pushing object creation down to subclasses

## What it teaches

The chapter motivates the Factory Method creational pattern through a
notification-sending service that starts with a single channel (email) and
gradually accumulates SMS, push, Slack, and chat channels. The lesson traces
the natural decay of the naive design: a service class that both decides
which channel object to build and orchestrates the sending grows a new
conditional branch for every channel, so every product request forces edits
to the same central class. That concentration of construction knowledge makes
the class fragile, hard to test, and a standing violation of the Open/Closed
Principle.

It deliberately walks through an intermediate refactor first — the "Simple
Factory," where all construction moves into one dedicated creation class.
The chapter is careful to note this is a pragmatic idiom, not one of the
canonical Gang of Four patterns. It improves things (callers stop building
objects themselves), but the factory itself still hoards a growing
switch-style decision, so the modification pressure has only relocated, not
disappeared.

Factory Method resolves this by decentralizing creation entirely: an abstract
creator declares a creation hook plus shared workflow logic that consumes
whatever the hook returns, and each concrete creator subclass overrides the
hook to produce exactly one product type. The four roles are: a product
interface (the contract all created objects satisfy), concrete products (each
with channel-specific internals behind an identical surface), an abstract
creator (owns the workflow, defers the "which object" question), and concrete
creators (a one-to-one, explicit pairing with a product). A second worked
domain — a document export system emitting several report formats through a
shared header/rows/footer sequence — shows the same shape transplanted.

## Key patterns & decisions

- **Simple Factory as an honest first step**: centralize construction in one
  class before reaching for the full pattern; acknowledge it merely relocates
  the conditional rather than eliminating it.
- **Creation hook + template workflow**: the abstract creator combines a
  deferred creation method with concrete shared behavior that uses the
  created object, so the flow is written once and the variation point is
  isolated.
- **One concrete creator per concrete product**: the mapping is explicit and
  1:1, replacing runtime branching with class selection.
- **Extension by addition, not modification**: a new channel or export format
  means two new classes and zero edits to existing code — the pattern's core
  payoff.
- **Program to the product interface**: clients and the creator's workflow
  only ever see the abstract product type, never a concrete class.
- **Conditional-chain smell as the trigger**: a growing if/else or switch
  over "type to instantiate" is the signal that creation logic wants its own
  polymorphic home.

## When to apply / trade-offs

Apply when the concrete type is only known at runtime, when construction is
complex or repeated, or when new variants arrive regularly and you cannot
afford to keep reopening a central class. The chapter implicitly concedes the
cost: every new product doubles the class count (product + creator), so for a
small, stable set of types the Simple Factory or even a plain conditional is
less ceremony. The client still has to pick a concrete creator somewhere —
the decision moves to the composition edge of the program, it does not vanish.

## Fidelity check

1. *Claim:* The chapter treats Simple Factory as a non-GoF stepping stone.
   *Support:* The capture explicitly says the Simple Factory is a common
   intermediate refactor, not a formal Gang of Four pattern, and that it ends
   up resembling the bloated code it replaced once types keep arriving.
2. *Claim:* The abstract creator carries shared behavior, not just the
   creation hook. *Support:* The capture describes the creator's send
   operation calling the creation method and then using the returned product,
   phrased as "the Creator defines the workflow, the subclasses fill in the
   details."
3. *Claim:* Adding a channel under Factory Method requires only new files.
   *Support:* The capture's WhatsApp scenario states you add two new classes
   (a product and its creator) with no modification to existing code and no
   regression risk.
