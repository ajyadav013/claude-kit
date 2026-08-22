---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/concert-ticket-booking-system.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Seat inventory booking: contention on scarce, individually addressable resources

## What it teaches
Ticket booking is the canonical "many buyers, few identical resources" problem. The
core insight in this design is that the unit of contention is the individual seat,
not the concert: each seat is modeled as a small state machine (available, reserved,
booked) that owns its own transition methods, so the double-booking check happens at
the finest possible granularity. A booking then aggregates a user, a concert, and a
set of seats into its own lifecycle (pending, confirmed, cancelled), which cleanly
separates "I hold these seats" from "the purchase went through" — the reserve step
and the confirm step are distinct transitions, leaving room for payment to fail in
between and for held seats to be released. Failure to acquire a seat is surfaced as
a domain-specific exception rather than a null or boolean, forcing callers to handle
contention as a first-class outcome. Search over concerts by artist, venue, and date
is kept in a central catalog service, which also owns booking creation.

## Key patterns & decisions
- Per-seat state machine with an availability enum and explicit book/release
  transitions — contention is resolved at the smallest lockable unit.
- Two-phase lifecycle split: seat reservation is a separate state from booking
  confirmation, so a payment window can exist between hold and purchase.
- Booking as an aggregate entity tying user, concert, and seat set with its own
  status enum and confirm/cancel operations, independent of seat state.
- Domain exception for an unavailable seat — contention is an expected business
  outcome with a named type, not a silent failure.
- Tiered seat types via an enum (standard, premium, VIP) so pricing tiers extend
  without new subclasses.
- Central singleton catalog/booking service handling concert registration,
  multi-criteria search, ticket booking, and cancellation.
- Requirements push non-functional concerns — fairness under load, waiting lists
  for sellouts, confirmations over email/SMS — that the entity model deliberately
  leaves to service-layer extension points.

## When to apply / trade-offs
Reuse this shape anywhere users compete for uniquely identified inventory: event
seats, appointment slots, parking spots, warehouse bin allocations. The
seat-granular state machine minimizes lock scope but multiplies the number of
stateful objects; a real system needs a timeout that auto-releases reserved seats
when payment stalls, or inventory leaks. The in-memory singleton is fine for the
interview but hides the hard production problems the requirements hint at:
fairness (queueing rather than thundering-herd retries), waiting lists, and
durable, idempotent payment confirmation. The named-exception approach is a good
contract but callers must translate it into retry/alternative-seat UX.

## Fidelity check
- Claim: each seat individually owns its availability state and transitions.
  Support: the capture describes a seat entity holding a status enum (available,
  booked, reserved) with its own methods to book and release itself.
- Claim: booking confirmation is modeled separately from seat reservation.
  Support: the capture lists a booking entity with a pending/confirmed/cancelled
  status enum and confirm/cancel methods, distinct from the seat's own
  reserved-versus-booked states.
- Claim: contention failure is a named domain exception.
  Support: the capture includes a custom seat-not-available exception used when
  a requested seat cannot be booked.
