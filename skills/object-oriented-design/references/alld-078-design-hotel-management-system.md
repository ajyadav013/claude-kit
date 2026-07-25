---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/hotel-management-system.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for a hotel booking and front-desk system

## What it teaches

The exercise covers the full front-desk lifecycle: a guest books a room for
a date range, later checks in, and eventually checks out; staff manage guest
records, room assignments, and billing along the way. The room inventory is
heterogeneous (single, double, deluxe, suite tiers with different prices),
payments arrive through multiple channels (cash, card, online), and the
requirements add operational expectations — concurrent bookings must not
double-allocate a room, and the design should scale to large room/guest
counts and support management reporting.

The reference decomposition is notable for running two parallel state
machines — one on the physical room, one on the reservation record:

- A guest entity with identity and contact fields.
- A room entity with a type, a price, and a status, plus behavior for the
  three lifecycle transitions (book, check-in, check-out). Room state is an
  enum: available, booked, occupied. Putting the transition methods on the
  room itself makes illegal jumps (e.g. check-in on an available-but-unbooked
  room) enforceable at the entity boundary.
- A room-type enum modelling the tier catalog instead of subclassing rooms.
- A reservation entity binding a guest to a room over check-in/check-out
  dates, with its own identifier and its own status enum (confirmed vs
  cancelled) and a cancellation operation. The booking paperwork and the
  physical room deliberately track state separately: cancelling a
  reservation and freeing the room are related but distinct transitions.
- A payment interface with concrete implementations per channel (cash and
  card are named), so billing logic is closed to modification when a new
  payment rail appears.
- A singleton hotel-management service exposing the workflows — add guests
  and rooms, book, cancel, check-in, check-out, take payment — and guarding
  shared state with synchronization so concurrent bookings stay consistent.
- A demo class that walks the whole lifecycle end to end.

## Key patterns & decisions

- Dual state machines: room status (available → booked → occupied → back to
  available) and reservation status (confirmed → cancelled) evolve
  separately and are reconciled by the service workflows.
- Behavior-on-entity for transitions: the room exposes book/check-in/
  check-out operations rather than having the service mutate a bare status
  field, keeping transition rules next to the state they protect.
- Enum-as-catalog for room tiers: type is data on the room, not a class
  hierarchy — new tiers are enum additions, not new subclasses.
- Strategy interface for payment channels, identical in spirit to the rental
  and auction problems in this repo: one abstraction, one concrete class per
  rail.
- Singleton service facade owning registries of guests, rooms, and
  reservations, with synchronized access as the concurrency mechanism (this
  problem uses lock-based synchronization where sibling problems use
  concurrent collections).
- Explicit lifecycle coverage in the API: cancel, check-in, and check-out
  are first-class service operations, not afterthoughts bolted onto booking.

## When to apply / trade-offs

The dual-state-machine idea is the transferable core: whenever a booking
artifact and a physical resource can diverge (no-shows, cancellations, early
checkouts), give each its own status and let workflows reconcile them —
collapsing both into one field creates impossible-to-represent states.
Enum-based room typing is simpler than inheritance but caps per-tier
behavioral variation; if tiers ever need different logic (not just price),
the enum becomes a liability. Coarse synchronization on a singleton is easy
to reason about but serializes all bookings; per-room locking or optimistic
checks scale better, and the stated "large number of rooms and guests"
requirement is where this in-memory design would first crack. The reporting/
analytics requirement is listed but no class in the inventory addresses it —
a gap worth noticing when using this page as a checklist.

## Fidelity check

1. Claim: room state is a three-value enum (available, booked, occupied) and
   the room entity itself exposes the transitions. Support: the class
   inventory lists a room-status enum with exactly those states and says the
   room class provides methods to book, check in, and check out.
2. Claim: reservations carry their own status separate from room status,
   limited to confirmed or cancelled. Support: the inventory describes a
   reservation-status enum with confirmed and cancelled values on the
   reservation entity, alongside its cancel operation.
3. Claim: concurrency is handled with synchronization on a singleton
   service. Support: the inventory states the hotel-management class is a
   singleton and handles concurrent access to shared resources using
   synchronization.
