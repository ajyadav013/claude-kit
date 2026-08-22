---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/online-shopping-service.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for an e-commerce storefront (Amazon-style)

## What it teaches

A compact decomposition of retail commerce into cart, order, inventory, and
payment concerns. The lesson is in the seams: the cart is a mutable
scratchpad, the order is an immutable-ish record with a fulfillment state
machine, the product owns its own stock arithmetic, and payment sits behind
an interface so the charging mechanism can vary without touching order
placement.

## Key patterns & decisions

- **Cart/order separation** — the shopping cart is a per-user working set
  (add, remove, change quantities, keyed by product) that only becomes an
  Order at checkout; browsing-time churn never touches order history.
- **Line-item indirection** — an OrderItem pairs a product with a quantity
  instead of the order referencing products directly; the order total is
  derived by summing line items, so pricing math lives in one place.
- **Fulfillment state machine** — order status is an enum walking pending →
  processing → shipped → delivered, with cancelled as an exit; tracking and
  history features are just reads of this state.
- **Inventory guarded by the product** — the product entity owns its
  quantity and exposes availability checks and decrements, putting the
  stock invariant next to the data instead of scattering it through
  checkout code.
- **Payment as a strategy interface** — a payment contract with a concrete
  card implementation decouples "an order needs paying" from "how money
  moves", the standard seam for adding wallets, COD, etc.
- **Singleton service facade with synchronization** — one service object
  registers users, adds products, searches the catalog, and places orders,
  using synchronized access to shared state to keep concurrent checkouts
  consistent.
- **User aggregates their order history** — the user record carries its
  list of orders, making profile and history views a direct traversal
  rather than a query concern.

## When to apply / trade-offs

This is the canonical starting skeleton for any storefront, marketplace, or
booking-with-inventory flow, and a good interview map of where the
invariants live (stock in Product, money math in Order, variation in
Payment). Trade-offs to name: broad synchronization on a singleton service
serializes checkouts — fine in one JVM, unacceptable at scale, where you
would reach for per-product atomic decrements or reservation records
instead. Deriving totals from line items at read time is simple but real
systems snapshot prices into the line item at purchase time so later
catalog edits cannot rewrite history — this design's Product-referencing
items leave that ambiguity open. Embedding the order list in the user
couples two aggregates that eventually need independent storage and paging.

## Fidelity check

1. **Claim:** payment is abstracted behind an interface with one concrete
   card-based implementation. **Support:** the class notes define a payment
   contract for processing charges and name a credit-card implementation of
   it.
2. **Claim:** the product entity itself manages stock levels and
   availability checks. **Support:** the capture describes the product as
   carrying a quantity plus methods to update it and to check whether the
   item is available, and the requirements make inventory upkeep a system
   duty.
3. **Claim:** the central service is a singleton that relies on
   synchronization for concurrent correctness. **Support:** the capture
   states the main service class enforces a single instance and handles
   simultaneous access to shared resources via synchronization, matching
   the requirement for consistency under concurrent requests.
