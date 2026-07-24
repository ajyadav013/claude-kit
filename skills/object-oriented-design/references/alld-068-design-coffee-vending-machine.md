---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/coffee-vending-machine.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Coffee vending machine: recipes as data, guarded dispensing, and concurrency at the inventory boundary

## What it teaches

This problem models a self-service coffee machine that offers several drink
types, takes payment, dispenses, gives change, and tracks ingredient stock —
all while serving several customers at once. The pedagogical core is the
separation between *what* a product is (a named drink with a price and a
recipe: a mapping of ingredients to required quantities) and *how* the
machine executes an order (check stock, take payment, decrement inventory,
dispense, alert on low stock).

The reference decomposition has a drink entity carrying its recipe, an
ingredient entity that owns its own quantity and guards updates with
synchronization, a small payment value object, and a singleton machine class
that seeds the menu and inventory, exposes menu display and selection, and
performs the feasibility check before committing an order. Concurrency is
exercised deliberately: the demo drives the machine from a thread pool to
simulate simultaneous customers, which forces the stock check and the stock
decrement to be safe under interleaving.

## Key patterns & decisions

- **Recipe-as-data**: each drink is defined by a declarative ingredient/
  quantity map instead of drink-specific preparation code, so adding a menu
  item is a data change, not a code branch.
- **Check-then-commit guarded by the resource itself**: a "do we have enough
  of everything" feasibility test precedes dispensing, and the quantity
  mutation is synchronized at the ingredient level so concurrent orders
  cannot both pass the check and jointly overdraw stock.
- **Fine-grained locking on the contended object**: synchronization lives on
  the individual ingredient's update method rather than one global machine
  lock, keeping unrelated orders from serializing on each other.
- **Singleton machine facade**: one instance owns menu, inventory, and the
  order workflow, giving a single front door for all user interactions.
- **Low-stock signalling as a requirement**: inventory tracking includes an
  alerting responsibility (notify when ingredients run low), pushing
  observability into the design rather than bolting it on.
- **Concurrency proven in the demo harness**: the entry point simulates
  parallel customers via an executor, treating thread safety as a tested
  behavior rather than a claimed property.

## When to apply / trade-offs

- The recipe-as-data move generalizes to any catalog-driven fulfillment
  system (meal kits, CI pipelines consuming quota, cloud resource
  provisioning): keep the product definition declarative and let one engine
  execute it.
- Per-ingredient locks scale better than a machine-wide lock but reintroduce
  the classic multi-resource hazard: an order touching several ingredients
  needs either a consistent lock order or a higher-level transaction to
  avoid check/decrement races across ingredients. The simple design accepts
  a small race window between the aggregate feasibility check and the
  per-ingredient decrements — fine for a toy, worth an explicit reservation
  step in production.
- Payment is modeled as a bare amount here; a real machine needs a payment
  state machine (collected → validated → change computed → refunded on
  failure) and an idempotent refund path when dispensing fails after money
  was taken.
- Singleton is convenient for one physical machine but, as always, trades
  away test isolation.

## Fidelity check

1. Claim: drinks carry a price plus a recipe expressed as ingredients and
   amounts. Support: the requirements say every coffee type has a specific
   price and a recipe of ingredients with quantities, and the drink class is
   described as holding name, price, and recipe.
2. Claim: ingredient quantity updates are protected for thread safety at the
   ingredient level. Support: the capture describes the ingredient entity as
   providing a synchronized quantity-update method, and thread safety under
   concurrent requests is an explicit requirement.
3. Claim: the machine validates sufficient stock before dispensing and then
   deducts it. Support: the capture names a sufficiency-checking operation
   that verifies ingredients for a selected coffee and a separate update
   operation that adjusts quantities after dispensing.
