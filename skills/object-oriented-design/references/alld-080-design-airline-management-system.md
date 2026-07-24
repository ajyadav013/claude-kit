---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/airline-management-system.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Airline management: separating inventory, reservation, and payment into dedicated managers

## What it teaches

How to decompose a booking-heavy domain into three distinct concerns that are
easy to conflate: *inventory* (flights, aircraft, seats — what exists and what
is free), *reservation* (bookings that bind a passenger to a seat on a flight at
a price, with their own lifecycle status), and *settlement* (payments with their
own status, decoupled from the booking record). Search is pulled out as its own
query component rather than being a method on the flight entity, and the
mutation-heavy operations (create/cancel bookings, process payments) are pushed
into single-instance manager classes so there is exactly one place where
consistency rules are enforced.

## Key patterns & decisions

- **Inventory vs. reservation split.** Flight/Aircraft/Seat describe what can be
  sold; Booking describes what *has been* sold. Seats carry their own status so
  availability is a property of inventory, while the booking carries the
  passenger, price, and booking status — two independent state machines.
- **Booking as the aggregate that ties the domain together.** One record links
  passenger + flight + seat + price + status, giving cancellation and refund a
  single anchor object.
- **Payment as a first-class entity with independent status.** Money state is
  not a boolean on the booking; it is its own object (method, amount, status),
  which is what makes refunds and failed-payment retries representable.
- **Dedicated query object for search.** Flight search (by origin, destination,
  date) is a separate component, keeping read paths out of the entity classes
  and leaving room to swap in an index later.
- **Singleton managers for mutation choke points.** Booking creation/cancellation
  and payment processing each run through a single-instance manager — the design
  concentrates concurrent-access control where double-booking would occur.
- **Top-level system facade.** A root class composes the managers and search and
  exposes the whole workflow, so callers see one API while internals stay
  partitioned.
- **Role-aware requirements.** The problem explicitly calls for passenger,
  staff, and administrator user types — a reminder that access control is part
  of the domain, not an afterthought.

## When to apply / trade-offs

- The inventory/reservation/settlement triangle recurs in every booking system
  (hotels, cinemas, rentals); getting the three lifecycles separated early is
  the main design win.
- Seat-level status plus a booking manager choke point is the interview-scale
  answer to double-booking; at service scale you would replace it with a
  database constraint or atomic compare-and-set per seat, plus a hold/expiry
  (two-phase) flow so seats are not locked while payment is pending.
- Singleton managers make the consistency story easy to state but create global
  mutable state; in production the same role is played by transactional
  repositories, not process singletons.
- The design names cancellations, refunds, and flight changes as requirements
  but the entity list only carries statuses — a real implementation needs
  explicit state-transition rules (which statuses may move to which) and
  compensation logic linking booking cancellation to payment refund.

## Fidelity check

1. *Claim: seats and bookings carry independent statuses.* Supported: the
   capture lists a seat entity with number/type/status and a separate booking
   entity holding flight, passenger, seat, price, and its own booking status.
2. *Claim: booking and payment mutations are funneled through single-instance
   managers.* Supported: the capture states both the booking manager and the
   payment processor follow the Singleton pattern, one managing
   creation/cancellation of bookings and the other payment processing.
3. *Claim: search is a separate component rather than an entity method.*
   Supported: the capture describes a dedicated flight-search class providing
   lookup by source, destination, and date, distinct from the flight class.
