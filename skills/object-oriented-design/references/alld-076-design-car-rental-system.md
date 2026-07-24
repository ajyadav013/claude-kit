---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/car-rental-system.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for a car rental and reservation service

## What it teaches

The exercise models a rental agency: customers browse an inventory of cars,
filter by attributes (vehicle type, daily price band, whether the car is free
for their dates), and place date-ranged reservations that can later be
amended or cancelled. Beyond the happy path, the requirements force three
production concerns into the design: availability tracking must stay in sync
with reservation lifecycle events, payments must be collected through
pluggable channels, and two customers booking simultaneously must not both
win the same car for overlapping dates.

The reference decomposition is a straightforward domain model plus one
service facade:

- A car entity carrying descriptive attributes (make, model, year, plate,
  per-day price) plus a mutable availability flag.
- A customer entity holding identity and driver's-license details — the
  legal prerequisite data the requirements call out explicitly.
- A reservation entity that ties one customer to one car over a start/end
  date range, computes a total price from the daily rate, and carries its own
  identifier so it can be modified or cancelled later.
- A payment-processor abstraction: an interface defining the payment
  contract, with concrete implementations per channel (the capture names
  card and PayPal variants). New payment methods become new implementations,
  not edits to booking logic — the strategy pattern applied to checkout.
- A singleton rental-service class that owns the car and reservation
  registries, exposes search/reserve/cancel/pay operations, and uses
  concurrent hash-map structures so simultaneous bookings do not corrupt
  shared state.
- A separate demo/entry-point class, keeping the service reusable.

## Key patterns & decisions

- Service facade over a domain model: entities stay mostly data-plus-
  invariants while one rental-system object hosts the workflows (search,
  reserve, cancel, pay).
- Strategy interface for payments: booking code depends on an abstract
  processor, and each payment rail is a swappable concrete implementation.
- Reservation as a first-class entity with its own ID and date range —
  availability is a derived question ("is there a reservation overlapping
  these dates?") rather than only a boolean on the car.
- Singleton service instance: a single authoritative in-memory registry of
  cars and reservations, which is what makes the concurrency story tractable.
- Concurrent collections instead of coarse locks: the shared car and
  reservation maps are lock-free-ish concurrent structures so parallel
  requests interleave safely.
- Criteria-based search as an explicit operation on the service (type,
  price range, date availability), decoupled from how inventory is stored.

## When to apply / trade-offs

This shape generalizes to any inventory-with-time-window booking domain
(equipment hire, venue booking, seat reservation). The key modelling lesson
is putting the date range on the reservation, not the asset — an availability
flag on the car alone cannot express future bookings, so real
overlap-checking must consult reservations. The singleton-plus-concurrent-map
approach is fine for a single-process interview answer but is the main thing
you would replace in production: cross-request consistency for overlapping
date ranges really needs transactional storage or per-car locking, because a
concurrent map only protects individual map operations, not the
check-then-reserve sequence. The payment strategy interface is the most
directly reusable piece — it isolates a volatile integration point behind a
stable contract.

## Fidelity check

1. Claim: search must support filtering by car type, price range, and
   availability. Support: the requirements state customers search for cars
   using criteria such as vehicle type, price band, and whether the car is
   available.
2. Claim: payments are modelled as an interface with per-channel concrete
   classes. Support: the class inventory describes a payment-processor
   interface implemented by credit-card and PayPal processor classes.
3. Claim: the central service is a singleton using concurrent data
   structures for thread safety. Support: the class inventory says the
   rental-system class follows the singleton pattern and uses concurrent
   hash maps to manage concurrent access to cars and reservations.
