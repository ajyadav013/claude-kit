---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/movie-ticket-booking-system.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for a seat-reservation booking platform (BookMyShow-style)

## What it teaches

How to decompose a cinema-ticketing domain into a small object graph whose
hardest problem is not the entities themselves but the concurrency around a
shared, finite resource: seats. The exercise walks from functional needs
(browse movies, pick a showing, pick seats, pay, confirm) to a class design
where every seat carries its own lifecycle state, and where the top-level
service serializes contention with concurrent collections rather than
coarse global locks.

## Key patterns & decisions

- **Catalog vs. inventory split** — Movie and Theater are stable catalog
  data; the Show entity is the join point (one movie, one theater, one time
  window) that owns the perishable inventory. Pricing and availability hang
  off the Show, not off the Movie.
- **Seat as a stateful cell** — each seat in a showing is its own object
  with position, a tier (regular vs. premium, driving price), and an
  availability status enum. Availability is per-show, not per-auditorium,
  because the same physical chair is sold independently for every screening.
- **Booking as an aggregate with a lifecycle** — a reservation groups a
  user, one showing, a set of chosen seats, and a computed total, and moves
  through a small state machine (awaiting payment → confirmed → cancelled).
  Modeling the pending state explicitly is what makes payment failure and
  seat release representable.
- **Enum-driven variability** — seat tiers and both lifecycle statuses
  (seat, booking) are enums rather than subclasses; variation is data, not
  hierarchy.
- **Singleton facade over the whole domain** — one system object exposes
  the admin operations (register movies/theaters/shows) and the customer
  operations (reserve, confirm, cancel), so there is exactly one authority
  arbitrating seat contention.
- **Concurrency via concurrent maps** — shared registries of shows and
  bookings live in thread-safe map structures so simultaneous reservation
  attempts for the same showing do not corrupt state; the design leans on
  fine-grained concurrent containers instead of one big lock.
- **Two actor roles, one model** — theater administrators mutate the
  catalog while customers mutate bookings; both operate through the same
  facade rather than parallel subsystems.

## When to apply / trade-offs

Apply this shape to any "claim a unit of finite, time-boxed inventory"
problem: event ticketing, airline seats, restaurant tables, parking slots.
The per-seat status object gives precise contention granularity but means
inventory objects are numerous (seats x shows); a bitmap or range model is
cheaper when seats are undifferentiated. The singleton facade is fine for
an interview-scale single process but becomes the bottleneck and a
scaling lie in a distributed deployment — real systems replace it with a
transactional store plus short-lived seat holds (with expiry), which this
design's pending-booking status only gestures at. Concurrent maps prevent
structural corruption but do not by themselves make "check seat free, then
book it" atomic; an implementer still needs a compare-and-set or lock per
show for the critical section.

## Fidelity check

1. **Claim:** availability must update in real time under simultaneous
   purchase attempts. **Support:** the requirements explicitly demand
   handling of concurrent bookings with seat availability kept current as
   users compete for the same seats.
2. **Claim:** the design distinguishes seat tiers with distinct pricing.
   **Support:** the requirements call for multiple seat categories such as
   normal and premium, and the seat entity carries both a type and a price
   field.
3. **Claim:** thread-safety is achieved with concurrent data structures on
   the shared registries. **Support:** the class notes state that
   multi-threading is handled through concurrent containers (a
   ConcurrentHashMap is named) guarding shared resources like shows and
   bookings.
