---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/ride-sharing-service.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Ride-sharing service: a ride lifecycle mediated by one concurrent service

## What it teaches

The core of this design is a mediator: passengers and drivers never talk to
each other directly. A single service object owns every interaction —
registering both parties, accepting ride requests, matching them to nearby
available drivers, and driving each ride through its lifecycle (requested,
accepted, started, completed, or cancelled). The ride itself is the central
entity binding a passenger, a driver, two locations, a status, and a fare.

The supporting entities are deliberately simple: passenger and driver records
carry identity, contact details, and current location, with the driver
additionally tracking an availability flag that the matcher consults.
Location is a small latitude/longitude value object used for both endpoints
of a trip and for proximity-based matching. Payment is its own record tied to
a ride with an amount and its own status, keeping money concerns separate
from trip concerns.

Two implementation stances matter. First, the service is a singleton — one
authoritative in-process broker for all state transitions, which makes the
consistency story tractable. Second, concurrency is addressed by choosing
thread-safe collections for the shared hot spots (the pool of pending
requests, the set of drivers and their availability) instead of wrapping
every operation in explicit locks. Notification of both sides on status
changes, fare computation, and payment processing are stubbed as named
extension points — the design tells you *where* those responsibilities live
without committing to a mechanism.

## Key patterns & decisions

- Mediator/service facade: one service object brokers all passenger-driver
  interaction; neither side holds a reference to the other except through a
  ride.
- Ride as a state machine: a status field advanced only by service methods
  (request, accept, start, complete, cancel), so every legal transition has a
  single owner.
- Concurrent collections over explicit locking for shared mutable pools
  (pending requests, driver registry) — pick data structures that make the
  common operations atomic.
- Driver availability as an explicit status flag, flipped by the lifecycle
  methods, so matching only ever considers free drivers.
- Location as a shared value object used for pickup, destination, and
  proximity matching alike.
- Payment split into its own entity with independent status, decoupling
  settlement from ride completion.
- Named placeholder methods for notification, fare calculation, and payment
  processing — seams identified up front for later strategy implementations.

## When to apply / trade-offs

This shape fits any two-sided marketplace or dispatch system: delivery
assignment, support-ticket routing, job schedulers matching work to workers.
The mediator keeps invariants (a driver serves one ride at a time; a ride has
exactly one driver) enforceable in one place. Trade-offs: the singleton
service is a scaling and testing bottleneck — in production this becomes a
horizontally scaled service with the same *logical* role, and consistency
moves to the datastore or a queue. Concurrent collections protect individual
operations but not multi-step invariants (check-availability-then-assign
still needs an atomic claim), which is the classic gap to probe in this
design. Stubbing fare/notification/payment is good sequencing discipline, but
each stub hides a real subsystem with its own failure modes.

## Fidelity check

1. Claim: all party interaction is funneled through a single service object
   built as a singleton. Support: the capture describes a main ride-service
   class using the singleton pattern that handles adding passengers and
   drivers plus requesting, accepting, starting, completing, and cancelling
   rides.
2. Claim: shared state is protected by concurrent data structures rather
   than manual locking. Support: the capture states that thread-safe map and
   queue types handle concurrent access to ride requests and driver
   availability.
3. Claim: fare computation, payments, and status notifications are declared
   as extension points rather than implemented. Support: the capture
   explicitly labels the notify-driver/passenger methods and the
   fare-calculation and payment-processing methods as placeholders.
