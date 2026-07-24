---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/elevator-system.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for a multi-car elevator dispatch system

## What it teaches

This is a classic concurrency-plus-scheduling LLD exercise. The problem asks
for a building with several elevator cars serving many floors, where riders
issue hall calls (pick me up at floor X) and cab calls (take me to floor Y).
The system's quality bar is not just correctness but service quality: cars
must be assigned to calls so that average wait time stays low, requests
travelling in the same direction get batched, and each car respects a hard
passenger-capacity ceiling. Because calls arrive from many riders at once,
every shared structure (per-car request queues, car position/direction state)
has to survive concurrent mutation without races.

The reference design decomposes the problem into a small set of collaborating
types rather than one monolithic controller:

- A direction enum with the two travel states (up, down) that drives both car
  movement and call-matching logic.
- A request value object pairing an origin floor with a destination floor —
  the atomic unit of work the system schedules.
- An elevator (car) entity that owns its capacity limit and its own pending
  request collection, and runs its own processing loop: it consumes queued
  requests concurrently with new ones arriving and steps between floors
  accordingly. Each car is effectively an independent worker with a mailbox.
- A controller that fronts the whole bank of cars. It is the single entry
  point for hall calls and implements the dispatch policy — the capture
  describes a nearest-car heuristic (choose the car closest to the requesting
  floor), with the requirements further asking that direction of travel be
  factored in so a car already heading toward you in your direction wins.
- A thin top-level system/demo class that wires everything together.

## Key patterns & decisions

- Controller-dispatches-to-workers: one coordinator object receives all
  external requests and routes each to the best of N autonomous car objects;
  cars never talk to each other.
- Per-car request queue: each elevator owns its own work backlog instead of
  the bank sharing one global queue, which localizes locking and lets cars
  run as independent threads/loops.
- Proximity-plus-direction dispatch heuristic: pick the closest car, biased
  toward cars already moving in the caller's direction — a greedy policy
  that approximates the real-world SCAN/collective-control behavior without
  global optimization.
- Request as an immutable value object (source floor, destination floor)
  separating "what the rider wants" from "how a car fulfills it."
- Capacity as an invariant on the car entity, enforced at the point a request
  is accepted rather than policed by the controller.
- Explicit thread-safety requirement: concurrent request intake and car
  movement mean queues and car state need synchronization or concurrent
  collections; races are called out as a first-class failure mode.

## When to apply / trade-offs

The controller/worker split fits any resource-pool scheduling problem
(thread pools, courier dispatch, charging bays): keep the assignment policy
in one place so you can swap the heuristic without touching worker logic.
The greedy nearest-car policy is simple and lock-friendly but can starve far
floors and ignores load balancing; production elevator algorithms add
direction-sweep ordering and re-assignment. Per-car queues reduce contention
but make global re-optimization (stealing a request from a busy car) harder —
a single shared priority queue is the opposite trade. The page is a design
skeleton: it specifies entities and responsibilities, and defers the actual
scheduling-order details to the linked language implementations.

## Fidelity check

1. Claim: the system must factor both proximity and travel direction into
   dispatch. Support: the requirements list says requests are prioritized by
   the direction of travel and by how near each elevator is to the calling
   floor.
2. Claim: each car owns its own pending-request collection and processes it
   concurrently while moving between floors. Support: the class inventory
   describes the elevator class as holding a capacity limit and a list of
   requests which it processes concurrently as it moves.
3. Claim: a dedicated controller class selects the optimal car for each user
   request. Support: the class inventory states the controller manages the
   multiple elevators and picks the elevator to serve a request based on the
   cars' proximity to the requested floor.
