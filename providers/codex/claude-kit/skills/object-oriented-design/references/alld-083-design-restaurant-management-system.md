---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/restaurant-management-system.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Restaurant operations as a single facade over independent domain lifecycles

## What it teaches
This problem exercises modeling a business with several loosely-coupled sub-domains
(menu, ordering, reservations, payments, staffing, reporting) behind one coordinating
service object. The interesting part is not any single entity but the recognition that
each sub-domain carries its own lifecycle: an order moves through a preparation state
machine, a payment moves through its own success/failure states, and a reservation is
a time-bound resource claim. The design keeps these lifecycles separate — an order does
not "know" how payment works, and a reservation is not entangled with the menu — while
a single restaurant-level facade wires them together and owns the shared collections.
Because waitstaff, kitchen, and customers all touch the same order and reservation
collections simultaneously, the design leans on thread-safe collection types rather
than coarse global locking, and it stubs out notification hooks (kitchen, staff) as
seams for future event-driven integration.

## Key patterns & decisions
- Facade/singleton coordinator: one restaurant-level service owns all sub-domain
  collections and exposes the whole use-case surface (order, reserve, pay, staff).
- Order lifecycle as an explicit enum-driven state machine (pending through
  preparing, ready, completed, with a cancel path) rather than boolean flags.
- Payment modeled as its own entity with its own status enum, decoupled from the
  order that triggered it — payment failure does not corrupt order state.
- Enum-typed payment methods so adding a new tender type is a data extension,
  not a control-flow rewrite.
- Concurrent collections (map/list variants safe under simultaneous readers and
  writers) instead of a global lock for shared order/reservation state.
- Notification methods left as intentional placeholders — an explicit extension
  seam for later observer/event wiring instead of premature messaging plumbing.
- Reservation treated as a first-class entity (party size, contact, time) rather
  than a field on a customer or table, keeping the booking sub-domain isolated.

## When to apply / trade-offs
Apply this shape when one deployable unit must coordinate several small business
domains and full microservice separation would be overkill. The singleton facade is
the main scaling liability: it centralizes every mutation, becomes a god-object
magnet as requirements grow, and makes testing require the shared instance. In a
production system the sub-domains (payments especially) would migrate behind their
own service interfaces, and the placeholder notifications would become real events.
Concurrent collections handle per-collection safety but not cross-entity invariants
— e.g., "charge exactly once per completed order" needs transactional coordination
these structures alone cannot give you.

## Fidelity check
- Claim: the design centralizes coordination in a singleton restaurant service.
  Support: the capture states the main restaurant class follows the Singleton
  pattern and provides the methods for menus, orders, reservations, payments,
  and staff management.
- Claim: concurrency is handled with thread-safe collections rather than locks.
  Support: the capture says multi-threading is implemented via concurrent data
  structures (a concurrent hash map and a copy-on-write list) protecting shared
  orders and reservations.
- Claim: order and payment progress are modeled as separate enum state machines.
  Support: the capture lists a distinct order-status enum (pending, preparing,
  ready, completed, cancelled) and a separate payment-status enum (pending,
  completed, failed) alongside a payment-method enum.
