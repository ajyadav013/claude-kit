---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/vending-machine.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# State-machine design for a vending machine

## What it teaches

The vending machine is the textbook vehicle for the State pattern: a device
whose valid operations depend entirely on where it is in a transaction
lifecycle. Instead of one class riddled with conditionals ("if money inserted
and product selected then..."), the design defines a state interface and one
concrete class per lifecycle phase — idle, ready (payment/selection in
progress), and dispensing. Each state class encodes exactly which actions are
legal in that phase and which transition they trigger; the machine object
holds a reference to the current state and forwards user actions to it.
Illegal sequences (dispensing before paying) become structurally impossible
rather than runtime-checked afterthoughts.

Around the state machine sit supporting decisions: money is modeled as fixed
enumerations of coin and note denominations (so arithmetic happens over a
closed set), inventory is a thread-safe map from product to quantity, and the
machine itself is a singleton because it represents one physical device.
Error paths — not enough money, product sold out — are treated as first-class
requirements, not exceptions bolted on later.

## Key patterns & decisions

- State pattern for transaction lifecycle: a state interface with idle, ready,
  and dispense implementations, each owning the behavior valid in that phase;
  transitions move the machine between them.
- Context object holds current state plus transaction data: the machine tracks
  the active state, the selected product, and the running payment total, and
  exposes the transition and payment operations.
- Denominations as closed enums: accepted coins and notes are enumerated
  types, making payment math a sum over known values and rejecting unknown
  denominations by construction.
- Thread-safe inventory via a concurrent map: product-to-quantity bookkeeping
  uses a concurrent hash map so stock checks and decrements survive parallel
  transactions.
- Singleton machine instance: one software object per physical device, giving
  all interactions a single consistent inventory and cash view.
- Explicit failure flows: insufficient funds and out-of-stock are enumerated
  requirements, forcing each state to define behavior (refuse, refund, reset)
  for them.
- Separated operator surface: restocking and cash collection are their own
  interface, distinct from the customer purchase flow.
- Change-making as part of dispense: returning the difference between payment
  and price is a required step of the dispense phase, not an optional nicety.

## When to apply / trade-offs

- Reach for the State pattern when an object's behavior differs per lifecycle
  phase and phases have crisp transitions — order checkout flows, connection
  handshakes, document approval chains all fit the same mold.
- The pattern trades conditional density for class count: three states is
  clean, but a dozen states with shared behavior starts to want a transition
  table or a state-machine library instead of hand-written classes.
- Enum denominations are simple and safe but rigid — supporting cashless
  payment later means the payment side needs an abstraction the enum approach
  does not provide.
- A concurrent map protects individual reads/writes but not multi-step
  invariants (check stock then decrement); a real implementation still needs
  an atomic reserve-or-fail step for the purchase path.

## Fidelity check

1. Claim: the lifecycle is split into three concrete state classes behind a
   common interface. Support: the capture names a state interface and idle,
   ready, and dispense implementations, each defining phase-specific behavior.
2. Claim: inventory thread safety comes from a concurrent hash map. Support:
   the capture states the inventory component manages products and quantities
   using a concurrent hash map for thread safety.
3. Claim: the machine is a singleton that also carries transaction context.
   Support: the capture says the machine class follows the Singleton pattern
   and maintains current state, chosen product, and accumulated payment, with
   methods for transitions and payment handling.
