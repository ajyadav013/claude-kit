---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/parking-lot.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for a multi-level parking facility

## What it teaches

This is the canonical warm-up problem for object-oriented design interviews:
model a physical facility (a parking garage) as a tree of cooperating objects
and make the mutation points safe under concurrency. The core lesson is
decomposition by physical containment — the whole facility owns floors, each
floor owns a fixed set of spots, and each spot is the smallest unit of state
(occupied or free, and by which vehicle). Business rules live at the level
where the data lives: the spot knows whether a given vehicle fits, the floor
knows how to scan for a free compatible spot, and the top-level object simply
delegates downward.

A second lesson is separating the vehicle taxonomy from the spot taxonomy.
Vehicles form a small inheritance family (car, motorcycle, truck under an
abstract parent) keyed by a size enum, and each spot advertises which size it
accepts. Matching a vehicle to a spot is then a comparison of enum values, not
a chain of type checks — new vehicle categories become a data change rather
than a control-flow change.

## Key patterns & decisions

- Singleton facility root: exactly one object represents the physical garage,
  so all entry/exit points funnel through one consistent view of availability.
- Containment hierarchy: lot holds floors, floors hold spots; each layer
  exposes park/unpark operations and delegates to its children.
- Spot as the unit of state: availability and the currently parked vehicle are
  tracked per-spot, making the free/occupied transition the only mutation.
- Size-enum compatibility matching: an abstract vehicle base class plus a size
  enumeration lets spot assignment be a simple size comparison, keeping the
  design open to new vehicle types.
- Coarse-grained lock on critical sections: concurrent access from multiple
  gates is handled by synchronizing the assign/release operations rather than
  by lock-free structures — simple and correct at parking-lot scale.
- Real-time availability as a first-class requirement: the model must be able
  to answer "what is free right now" cheaply, which motivates keeping counts
  or scans local to each floor.
- Suggested extensions kept optional: a factory for constructing vehicles from
  input and an observer channel for notifying customers about freed spots are
  named as add-ons, not baked into the core model.

## When to apply / trade-offs

- Apply the containment-hierarchy shape whenever a domain has literal physical
  nesting (building → floor → room, warehouse → aisle → bin); it keeps each
  class small and the delegation obvious.
- The singleton is defensible here because the software instance maps 1:1 to a
  physical facility, but it costs testability and multi-facility reuse — a
  dependency-injected single instance achieves the same guarantee with less
  coupling.
- Synchronizing whole park/unpark operations is easy to reason about but
  serializes all gates; per-floor or per-spot locking (or an atomic
  reservation step) scales better if contention is real.
- Enum-based compatibility is coarse: it cannot express "a truck occupies two
  adjacent spots" without redesign, so validate the granularity of the size
  model against real requirements first.

## Fidelity check

1. Claim: the design guarantees a single facility instance. Support: the
   capture states the top-level parking-lot class uses the Singleton pattern
   so only one instance of the lot can exist.
2. Claim: thread safety is achieved with coarse locking rather than concurrent
   data structures. Support: the capture says multi-threading is handled by
   applying the synchronized keyword to critical sections.
3. Claim: factory and observer are positioned as optional add-ons, not core.
   Support: the capture's design-patterns list labels Factory (vehicle
   creation from input) and Observer (notifying customers of open spots) as
   optional extensions alongside the mandatory Singleton.
