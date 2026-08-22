---
source: https://algomaster.io/learn/lld/composition
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Composition: the ownership-and-lifecycle form of "has-a"

## What it teaches

This chapter defines composition as the tightest of the class relationships in
object-oriented design. Where a plain association is just "these classes know
about each other" and aggregation is a loose grouping of parts that outlive
the whole, composition means the containing object is the sole creator, owner,
and destroyer of its parts. The litmus test the chapter drills in: if a part
carries no meaning or identity on its own, and it disappears the moment its
container disappears, model the relationship as composition.

The running domain example is an order containing line items. A line item is
just a record of one product's quantity and price inside a specific order —
nobody else in the system ever holds one, it is manufactured inside the order
when an item is added, and it evaporates when the order is discarded. A
second example, a car built from an engine, transmission, and chassis, shows
that a whole can compose several distinct part types at once, none of which
is ever shared between two cars simultaneously.

The chapter also connects composition to the classic GoF advice of preferring
it over inheritance: assembling behavior from swappable components (a vehicle
holding some engine abstraction that could be petrol, electric, or hybrid)
gives flexibility that a rigid subclass hierarchy cannot, and keeps units
independently testable.

## Key patterns & decisions

- **Filled-diamond composition semantics**: the whole creates, exclusively
  owns, and destroys its parts; UML marks this with a solid diamond on the
  whole's end, versus the hollow diamond of aggregation and the plain line of
  association.
- **Internal part construction as the structural tell**: in a true
  composition the container's methods take raw data and build the part
  objects themselves; if fully-formed parts are handed in from outside, the
  relationship has drifted toward aggregation.
- **Lifecycle coupling eliminates cleanup**: because parts live and die with
  the whole, there are no orphaned objects or dangling references to manage —
  destruction of the container implies destruction of everything it composed.
- **Exclusivity test for choosing the relationship**: a part shared by
  several wholes (a song appearing in many playlists) signals aggregation; a
  part bound to exactly one whole (a line item in one order) signals
  composition.
- **Composition over inheritance**: building complex behavior by plugging
  small components into a container avoids brittle deep hierarchies and lets
  behavior be swapped at runtime by substituting a different part behind an
  interface.
- **Three-way comparison axis**: association, aggregation, and composition
  differ along ownership, lifecycle dependence, coupling tightness, part
  reusability, and who constructs the parts — a compact decision table for
  design reviews.

## When to apply / trade-offs

Reach for composition when the part is meaningless standalone, the whole
should govern its lifetime, and the part is never shared. The cost is low
reusability of the part type outside its container and the tightest coupling
of the three relationships — which is fine precisely because the part was
never meant to travel. If you find yourself wanting to move a part between
containers or keep it alive after the container dies, downgrade to
aggregation. As an inheritance alternative, composition trades the
convenience of inherited behavior for looser coupling, runtime swappability,
and easier mocking in tests.

## Fidelity check

1. *Claim: composition parts are constructed inside the whole, not passed
   in.* The capture explains that the order's add-item operation receives raw
   product data and internally builds a new line item, and calls this the key
   structural difference from aggregation, where parts arrive from outside.
2. *Claim: UML distinguishes composition with a filled diamond.* The capture
   states the filled diamond sits at the whole's end of the connector,
   contrasting it explicitly with aggregation's hollow diamond and
   association's plain solid line.
3. *Claim: the chapter ties composition to the GoF "favor composition over
   inheritance" principle.* The capture quotes that principle and illustrates
   it with a vehicle composing an engine interface whose concrete
   implementation (petrol/electric/hybrid) can be swapped, yielding
   decoupled, testable code.
