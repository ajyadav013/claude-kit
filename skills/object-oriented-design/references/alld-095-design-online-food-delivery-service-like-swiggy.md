---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/food-delivery-service.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for a three-sided food-delivery marketplace

## What it teaches

How to decompose a marketplace with three independent actor types (people
ordering food, restaurants fulfilling menus, couriers moving the food) into a
small set of collaborating entities, with a single facade that owns
registration, ordering, and notification concerns. The exercise is less about
any one class and more about identifying which concepts deserve their own type
versus which are just fields on another type.

## Key patterns & decisions

- **Three-actor entity split**: the ordering party, the fulfilling business,
  and the courier are modeled as separate top-level entities rather than
  variants of one "user" type, because each has different data and a different
  lifecycle in the system.
- **Menu as owned collection**: a restaurant aggregates its menu entries and
  exposes add/remove operations, so menu mutation goes through the owner
  rather than being edited from outside.
- **Order line-item indirection**: an order does not reference menu entries
  directly; a small line-item type pairs the chosen dish with a quantity,
  keeping catalog data (price, description) separate from purchase data
  (how many).
- **Lifecycle as an enum state machine**: order progress is a closed set of
  named states running from creation through confirmation, kitchen prep,
  courier transit, and completion, with a cancelled branch — no free-form
  status strings.
- **Availability flags on both sides**: menu entries carry an availability
  bit (restaurants can pull dishes without deleting them) and couriers carry
  one too (assignment only targets free agents).
- **Singleton service facade**: one central service object is the sole entry
  point for registering all three actor types, browsing, placing/cancelling
  orders, advancing status, matching couriers to orders, and fanning out
  notifications to all interested parties.
- **Consistency under concurrency stated as a requirement**: the problem
  explicitly demands correct behavior when many orders arrive at once, pushing
  the design toward the facade serializing state changes.

## When to apply / trade-offs

- Use this decomposition whenever a domain has multiple actor roles with
  distinct data and duties — collapsing them into one "user with a role flag"
  couples unrelated lifecycles.
- The line-item pattern generalizes to any cart/order domain: never let an
  order mutate catalog objects; snapshot what was bought and how much.
- The singleton facade keeps the interview-scale design simple, but it is a
  known scaling and testability liability: in a real service you would split
  it into focused services (ordering, dispatch, notification) and drop the
  singleton in favor of injected instances.
- Status-enum state machines are cheap insurance; the cost is that adding a
  state touches every transition check, which is exactly the compiler-assisted
  reminder you want.

## Fidelity check

1. Claim: the design models customers, restaurants, and delivery agents as
   three separate entity types. Support: the capture's class inventory lists a
   customer entity holding contact details, a restaurant entity holding
   address plus menu, and a delivery-agent entity holding contact details plus
   an availability flag as distinct numbered classes.
2. Claim: order lifecycle is a closed enum from pending through delivered
   with a cancelled branch. Support: the capture names an order-status
   enumeration whose members cover pending, confirmed, preparing,
   out-for-delivery, delivered, and cancelled states.
3. Claim: a singleton facade owns registration, order placement, status
   updates, courier assignment, and notifications. Support: the capture
   describes the main service class as following the singleton pattern and
   enumerates exactly those responsibilities (registering all actor types,
   placing/cancelling orders, updating status, assigning agents, and sending
   notifications to all three parties).
