---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/online-stock-brokerage-system.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for a retail stock-trading platform

## What it teaches

How to model order-driven trading with polymorphic order types and
exception-signaled business-rule violations. The interesting move relative
to the other commerce problems in this repo is the abstract Order base
class: buying and selling share identity, status, and bookkeeping but
diverge in execution semantics, so execution is deferred to subclasses
instead of being switched on a flag.

## Key patterns & decisions

- **Separation of identity, money, and holdings** — User (who you are),
  Account (cash balance with deposit/withdraw), and Portfolio (which
  stocks you hold) are three distinct objects, so cash-sufficiency and
  share-sufficiency checks land on different entities.
- **Template/polymorphic order hierarchy** — an abstract order captures the
  shared shape (account, stock, quantity, price, status) and declares an
  abstract execute step; BuyOrder and SellOrder each supply their own
  execution behavior. Adding a new order kind (limit, stop) extends the
  hierarchy rather than editing a switch.
- **Order lifecycle enum** — orders progress through pending, executed, or
  rejected states, making failed validations a first-class recorded
  outcome, not a silent drop.
- **Domain exceptions as rule enforcement** — dedicated exception types for
  not-enough-cash and not-enough-shares turn business-rule violations into
  typed control flow the caller must confront, rather than boolean returns
  that are easy to ignore.
- **Mutable market data on the stock entity** — the stock object exposes a
  price-update hook, sketching where a real-time quote feed would plug in.
- **Singleton broker facade** — a single broker object owns account
  creation, the stock registry, and order intake/processing, giving one
  serialization point for concurrent trading requests (consistency under
  concurrency is an explicit requirement).

## When to apply / trade-offs

Reach for the abstract-order pattern whenever operations share bookkeeping
but differ in effect — payments vs. refunds, uploads vs. deletes, debits
vs. credits. Typed domain exceptions shine where violating an invariant
must abort a workflow (finance, inventory), though they cost more than
result objects in hot paths and are clumsy across async boundaries. The
gaps to be honest about: execute-on-the-order implies immediate fills — a
real brokerage needs an order book, matching engine, and a settlement
phase (settlement is listed as a requirement but no settlement entity
appears in the class list). Likewise, balance-check-then-execute must be
atomic per account or two concurrent orders can both pass validation; a
singleton facade only solves that within one process.

## Fidelity check

1. **Claim:** buy and sell are subclasses of an abstract order with an
   abstract execution method. **Support:** the capture describes Order as
   an abstract base holding common fields and declaring execute() for
   concrete BuyOrder/SellOrder classes to implement.
2. **Claim:** insufficient cash and insufficient holdings are modeled as
   distinct custom exceptions. **Support:** the class list names two
   dedicated exception types, one for funds shortfalls and one for stock
   shortfalls, tied to the requirement that the system validate balances
   and availability.
3. **Claim:** cash and holdings live on separate entities. **Support:** the
   capture gives Account a balance with deposit/withdraw operations while a
   separate Portfolio object tracks owned stocks with add/remove methods.
