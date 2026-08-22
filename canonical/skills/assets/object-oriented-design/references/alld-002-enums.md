---
source: https://algomaster.io/learn/lld/enums
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Enums as compiler-checked domain vocabularies and transition guards

## What it teaches

Why a closed set of named constants beats both raw strings (typo bugs the
compiler cannot see) and raw integers (magic numbers nobody can read) for
modeling states, roles, and categories. It then escalates: enums are not just
labels — in most languages each member can carry data and behavior, turning
what would be a fragile external lookup table into a self-contained domain
type, and combining with exhaustive switch handling to make state machines
compiler-audited.

## Key patterns & decisions

- **Closed-set typing over stringly typing**: when a value can only be one of
  a fixed list, declare that list as a type; misspelled strings compile
  silently and fail at runtime, whereas an invalid enum member fails at
  compile time.
- **Magic-number elimination**: named members document intent at the call
  site — a status comparison reads as domain language instead of an opaque
  integer test.
- **Data-carrying members**: attaching a payload to each member (the chapter
  uses coin denominations and per-payment-method fee rates) keeps constant
  and associated value adjacent, removing the classic bug where a name array
  and a value array fall out of sync.
- **Enum-driven state machine**: order status modeled as an enum with a
  forward-only advance operation — transitions go placed → confirmed →
  shipped → delivered, never backwards and never skipping — so the legal
  lifecycle is encoded once instead of re-checked ad hoc everywhere.
- **Guarded irreversible actions**: cancellation is allowed only in
  pre-shipment states, enforced by comparing against enum members rather than
  matching strings.
- **Exhaustiveness as a refactoring net**: adding a new member (a returned
  status, a wallet payment method) makes the compiler flag every switch that
  has not handled it, turning extension into a checklist instead of a hunt.

## When to apply / trade-offs

- Default to an enum for anything state-like: order phases, user roles,
  vehicle categories, compass directions — any set that changes rarely and
  must never admit outside values.
- Data-carrying members shine when the payload is small, static, and
  one-per-member (fees, display names); once values need runtime
  configuration or per-tenant variation, move them out to config and keep the
  enum as the key.
- Encoding transitions in one advance method centralizes lifecycle logic but
  couples the enum to ordering semantics; for complex graphs (multiple
  branches, parallel states) a dedicated state-machine structure scales
  better than a switch.

## Fidelity check

1. Claim: the chapter motivates enums via a silent string-typo failure mode.
   Support: the capture opens with an order-status scenario where a
   misspelled status string compiles without warning and the defect only
   surfaces when a customer's order is never processed.
2. Claim: enum members can embed their own data, replacing lookup tables.
   Support: the capture's coin example gives each denomination its cent value
   directly on the member, and the payment-method enum carries a fee
   percentage per member so no separate table must be kept in sync.
3. Claim: the worked example enforces a forward-only status chain with
   cancellation restricted to pre-shipping. Support: the capture states the
   advance operation permits only the placed-to-delivered sequence with no
   jumps or reversals, and the cancel operation returns a failure result when
   invoked after shipment.
