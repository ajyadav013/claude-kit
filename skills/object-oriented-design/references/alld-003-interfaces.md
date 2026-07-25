---
source: https://algomaster.io/learn/lld/interfaces
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Interfaces as contracts: program to the abstraction, inject the implementation

## What it teaches

The single most leveraged decoupling move in OOP: separate what a component
promises to do from how any particular class does it. A consumer that depends
only on a contract can be handed any conforming implementation — a real
provider, a not-yet-written one, or a test double — without changing a line
of its own code. The chapter builds this up through two parallel worked
domains (payment providers, alert channels) to show the pattern is
domain-independent.

## Key patterns & decisions

- **Contract/implementation split**: an interface declares required
  operations only; each implementing class supplies its own internals while
  honoring the same surface, so callers reason about the promise, not the
  mechanism.
- **Polymorphic substitution**: multiple implementations of one contract are
  interchangeable at the call site — the remote-control analogy: identical
  buttons drive a TV, soundbar, or projector, each reacting in its own way.
- **Dependency injection through interface-typed constructors**: the consumer
  (a checkout service, an alerting service) receives its collaborator from
  outside rather than constructing a concrete one internally; the injection
  point being interface-typed is what makes the decoupling real.
- **Runtime swappability**: which implementation is wired in becomes a
  deployment/configuration decision — the chapter demonstrates exchanging
  payment providers between two calls with zero consumer changes.
- **Test-double enablement**: because the consumer only needs "something
  satisfying the contract," unit tests substitute mocks, and each concrete
  implementation is testable in isolation from the others.
- **Open-for-extension integration**: adding a new provider or notification
  channel means writing one new implementing class; existing consumers accept
  it immediately with no modification.
- **Configuration-driven wiring**: in production the chosen implementation is
  selected from config or environment, keeping business logic untouched
  across channel/provider changes.

## When to apply / trade-offs

- Introduce an interface at any seam where you foresee multiple providers,
  need test isolation, or want to quarantine a volatile third-party
  dependency — payments, notifications, storage are the classic candidates.
- Do not interface everything: a contract with exactly one plausible
  implementation forever is indirection without benefit. The value appears at
  boundaries, not inside cohesive modules.
- Interface-typed injection pushes construction/wiring responsibility
  outward; something (composition root, factory, DI container) must now make
  the choice, which is a small structural cost for large flexibility.
- This is the mechanism behind the dependency-inversion principle and the
  ports-and-adapters style: same idea, larger scale.

## Fidelity check

1. Claim: the chapter defines an interface as a behavioral contract that
   omits implementation. Support: the capture repeatedly frames it as
   "defines the what, classes provide the how," with the remote control as
   the contract and the various devices as differing implementations of the
   same buttons.
2. Claim: the payoff example is a checkout service that depends on a payment
   contract, not a concrete provider. Support: the capture highlights that
   the service's constructor accepts the gateway abstraction rather than a
   specific provider class, and names this pattern dependency injection,
   noting it works only because the dependency is typed as the interface.
3. Claim: the alerting example shows extension without modification and
   config-driven channel selection. Support: the capture states that adding
   a new channel (e.g. a pager-style notifier) requires only a new
   implementing class the alert service accepts unchanged, and that in a real
   system the active channel would be read from configuration or environment
   with the alerting logic untouched.
