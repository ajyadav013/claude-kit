---
source: https://algomaster.io/learn/lld/encapsulation
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Encapsulation: private-by-default state behind a validated interface

## What it teaches

Encapsulation bundles an object's state together with the only operations
allowed to touch that state, and blocks every other access path. The chapter
frames it as two halves working together: hide the data, then expose a small
set of controlled entry points. Its analogy is a bank vault reached only
through an ATM — outsiders get a handful of sanctioned operations and never
see (or depend on) how the bank stores or validates anything internally, so
the bank is free to rework its internals without breaking any customer.

The mechanics are the familiar language features: visibility modifiers
(private for state, protected for subclass-shared internals, public for the
sanctioned surface) plus accessor/mutator methods that gatekeep reads and
writes. The chapter's operating rule is to default everything to private and
promote to public only deliberately.

Two worked designs carry the lesson. A bank-account class keeps its balance
unreachable from outside; the only mutation paths are a deposit operation and
a withdrawal operation, each of which enforces its own business rules before
touching state, plus a read-only balance accessor. Because every path into
the state validates first, the object can never be driven into an invalid
condition by external code.

The second design applies encapsulation as a security measure. A
payment-processing class accepts a raw card number in its constructor and
immediately converts it to a masked form via a private helper; the raw value
is never retained as a field at all. Even a debugger or accidental log
statement of the object reveals only the masked representation. Callers see a
minimal surface — construct, then invoke the payment operation — and the
masking policy can change later by editing one private method with zero
caller impact.

## Key patterns & decisions

- Private-by-default visibility: start every field and helper private,
  expose only what the contract genuinely requires.
- Validated mutators: state changes go through methods that enforce
  invariants, so the object cannot enter an invalid state from outside.
- Read-only accessors: expose observation of state without exposing the
  storage itself or a write path.
- Constructor-time sanitization of secrets: transform sensitive input into a
  safe representation immediately and never store the raw value, defeating
  debugger/log/reflection leaks.
- Change containment: because internals are unreachable, storage and policy
  can be reworked in one place without rippling to callers.
- Interface-not-implementation contract: callers learn what an object can
  do, never how it does it.

## When to apply / trade-offs

Apply whenever an object has invariants worth defending (balances, quotas,
lifecycle state) or holds sensitive data that must not escape in raw form.
The chapter distinguishes it from mere data protection: the maintainability
payoff — being able to rewrite internals freely — is at least as important as
the safety payoff. The cost is boilerplate (accessors, mutators) and a
slightly wider class; the implicit trade-off is that a mutator pair that just
mirrors the field adds ceremony without protection, so accessors should earn
their keep by validating or restricting.

## Fidelity check

1. Claim: the chapter defines encapsulation as data hiding plus controlled
   access in one unit. Support: the capture opens by describing grouping of
   variables and their operating methods into a single class while
   restricting direct access, and compresses it to a hiding-plus-control
   formula.
2. Claim: the recommended default is private everything, then selectively
   publish. Support: the access-modifier section states the general rule as
   making members private by default and only exposing what needs to be
   public.
3. Claim: the payment example never stores the raw card number, masking it
   at construction via a private method. Support: the capture's
   PaymentProcessor walkthrough says the constructor masks immediately so
   even reflection or debugging only reveals the masked version, and that
   changing the masking format later touches a single private method.
