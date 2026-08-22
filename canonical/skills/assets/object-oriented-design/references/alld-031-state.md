---
source: https://algomaster.io/learn/lld/state
author: algomaster.io (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# State pattern: one class per state instead of switch-riddled mode flags

## What it teaches

The running example is a vending machine that is always in exactly one of
four modes — idle, item-selected, money-inserted, dispensing — and whose three
operations (select item, insert coin, dispense) must mean something different
in each mode: dispensing while idle is an error, paying before selecting is
disallowed, selecting during dispensing is ignored. The naive build keeps an
enum field and branches on it inside every method. That works small but rots:
identical mode checks are duplicated across methods; introducing a new mode
(out-of-stock, maintenance) forces edits to every branch block in every
method, violating Open/Closed; and one class ends up owning transitions,
business rules, and per-mode behavior at once, breaching Single
Responsibility and resisting testing.

The State pattern relocates each mode's behavior into its own class behind a
shared state interface. The context (the machine) holds a current-state
reference and blindly forwards every operation to it. Crucially, the state
objects themselves decide and perform transitions: each interface method
receives the context, so a state can read shared data and install the
successor state on the context. The traffic-light analogy: each color knows
its own behavior and its own next color; the light just runs whatever state
is active.

## Key patterns & decisions

- One class per state: all logic for "this action in this mode" lives in that
  mode's class, killing duplicated conditionals across methods.
- Context-as-parameter: every state method takes the context, enabling states
  to read shared fields and trigger transitions themselves.
- State-driven transitions: successor selection is embedded in the states, not
  centralized in a conditional table inside the context.
- Delegation-only context: the client-facing class keeps the current state and
  shared data, and forwards every call — it appears to change class at
  runtime.
- Open/Closed extension: adding out-of-stock or maintenance (or an archived
  document state) means writing one new class; no existing state or context
  code changes.
- Explicit rejection of invalid actions: every state implements the full
  interface, making no-op or error responses to out-of-place actions a
  deliberate, visible decision rather than a fall-through.
- Domain transfer: a document workflow (draft → under-review → published, with
  unpublish looping back to draft) shows the same shape governing permission
  rules — draft allows edit/submit, review allows approve/reject, published
  is read-only.

## When to apply / trade-offs

Use when an object has several distinct modes with genuinely different
behavior per operation and the mode set is likely to grow. If states are few,
stable, and behavior differences are trivial, an enum plus branches is
honestly simpler — the chapter concedes the switch approach works for small,
predictable systems. The pattern's cost is class-count and indirection; its
payoff is isolated, individually testable state logic and additive extension.

## Fidelity check

1. Claim: the naive enum/switch design forces multi-site edits per new state.
   Support: the capture says supporting out-of-stock or maintenance modes
   would require updating the branch blocks in every method, flagged as an
   Open/Closed violation.
2. Claim: states install their own successors. Support: the capture describes
   state methods receiving the context precisely so a state can set the next
   state on it, and defines state-driven transitions as a core characteristic
   of the pattern.
3. Claim: certain operations must be refused per mode. Support: the capture
   enumerates rules like rejecting coin insertion before an item is selected
   and ignoring selection while dispensing, and the document example makes
   published documents read-only except for unpublishing back to draft.
