# Digest: Design a Vending Machine

- **Source:** https://x.com/Harry_The_Nerd/status/2060348729929175403
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** LLD (low-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### State Pattern for lifecycle-heavy objects

**What it is.** When an object's valid operations depend on which phase of its lifecycle it is in, model each phase as its own class instead of guarding every method with nested conditionals. The context object (here, the vending machine) keeps a reference to the current state object and forwards every user action to it; each state class encodes only the behavior legal in that phase and decides which state comes next.

**When to use it.** Any entity whose behavior branches on a mode/phase variable in multiple methods — payment flows, order lifecycles, connection handshakes, document workflows. The tell is the same mode check repeated across several methods.

**Trade-offs.** More classes and some ceremony for simple cases; in exchange, adding a phase becomes a new class rather than edits scattered through existing conditionals, and each phase's rules are auditable in one place. The article's context class ends up containing no conditional logic at all — pure delegation.

### Uniform state interface

**What it is.** Every state class implements one shared interface covering the full action set (insert money, select product, dispense, return change), so the context can call any state identically without knowing which one is active.

**When to use it.** Whenever applying the State Pattern; it's the mechanism that makes delegation branch-free.

**Trade-offs.** Each state must implement actions that are meaningless for it (see fail-fast below) — a small amount of boilerplate that buys polymorphic dispatch.

### Fail fast on actions invalid for the current phase

**What it is.** Actions that make no sense in a given state raise an error rather than being silently ignored. In the idle phase, only inserting money is accepted; selecting a product or requesting change with nothing in progress is rejected loudly.

**When to use it.** Any state machine: it converts protocol misuse into an immediate, localized failure instead of a corrupted flow discovered later.

**Trade-offs.** Callers must handle errors, but the alternative — no-op or best-effort behavior — hides sequencing bugs.

### Explicit transition topology with a conditional shortcut

**What it is.** The machine's four phases form a fixed loop: idle → money-inserted → dispensing → returning-change → idle. Transitions are decided inside states: the money-inserted phase accumulates additional deposits into the running balance (adds, never replaces) and validates before advancing; the dispensing phase branches on the remaining balance — leftover money routes through the change-return phase, an exact-payment balance jumps straight back to idle, skipping the change phase entirely.

**When to use it.** Design the transition graph up front and let each state own its outgoing edges; allow conditional edges that skip phases with nothing to do.

**Trade-offs.** Transition logic distributed across states is harder to see in one glance than a central table, but it keeps each state self-contained.

### Shared context stored on the machine, not in states

**What it is.** Data that must survive a transition — the product chosen and the running balance — lives on the context object. The money-inserted state records the selection; the dispensing state later reads it to know what to eject. States themselves stay stateless with respect to a particular transaction.

**When to use it.** Whenever one phase produces information a later phase consumes. Putting it on the context is the standard hand-off channel in the State Pattern.

**Trade-offs.** The context grows fields that only some states care about; the alternative (passing data through transition calls or storing it inside state objects) couples states together or breaks state reuse.

### Validate before committing to a transition

**What it is.** Before accepting a product selection, the money-inserted phase runs two checks: the item exists in inventory, and the deposited balance covers its price. Only after both pass is the selection recorded and the transition taken.

**When to use it.** Gate every state transition on its preconditions at the boundary, so downstream states can assume a valid context (dispensing never has to re-check affordability).

**Trade-offs.** None significant; the checks must live somewhere, and the entry gate is the cheapest place.

### One abstract product base class instead of parallel product classes

**What it is.** Chips, drink, and chocolate classes would be structurally identical — each is just a name, a quantity, and a price. The article collapses them into a single abstract Item base holding the shared attributes, with thin subtypes extending it. A new product kind (e.g. candy) is a new subclass; no existing code changes.

**When to use it.** When candidate classes differ only in identity, not structure or behavior — that's duplication (a DRY violation), and the fix is a shared base. The extension-without-modification property is the Open-Closed Principle in miniature.

**Trade-offs.** If subtypes never diverge behaviorally, even the subclasses may be unnecessary versus a plain type field — the article stops at the base-class step.

### Keyed map for inventory lookup

**What it is.** Inventory is a name→Item map, giving O(1) product lookup; a list would require a linear scan per lookup. Dispensing decrements the item's quantity and removes the entry entirely when it reaches zero, so the map only ever holds stock that actually exists.

**When to use it.** Any collection queried by a unique key more often than iterated.

**Trade-offs.** Standard map-vs-list: constant-time access at the cost of ordering guarantees; removal-at-zero keeps "exists in inventory" and "in stock" the same check.

### Separate selection from fulfillment

**What it is.** Choosing a product and physically ejecting it are modeled as distinct states rather than one action. Selection validates and records intent; dispensing performs the side effects (deduct price, decrement stock, eject).

**When to use it.** Whenever intent-capture and irreversible execution are genuinely different responsibilities — mirroring real hardware (button press vs. motor run) and, more generally, order-then-fulfill flows. It also gives the side-effecting step a single, well-defined home.

**Trade-offs.** One more state and transition than the minimal design; the payoff is a flow that maps to the real process and isolates the mutation-heavy step.

## Not absorbed

- **Series framing** ("Low-Level Design series #4") — interview-prep positioning, not design content.
- **Conversational asides** (the "sigh" about moving parts, the "That's all, folks" sign-off) — tone, no substance.
- **Main / Output sections** — a demo driver and its console output shown as code images; the images did not survive the text capture and a walkthrough adds nothing beyond the states already covered.
- **Engagement metrics** (views/likes/reposts at the foot of the post) — platform chrome.

## Fidelity check

**Post count in capture:** 1 (single long-form article post; `postCount: 1` in the harvest JSON).

**Article outline as the author structured it:**
1. Overview (Problem Statement)
2. Entities & Classes
3. 1. Item (Base Class + Subtypes)
4. What & Why the State Pattern? (includes the four-state list and shared interface)
5. 2. IdleState
6. 3. MoneyInsertedState
7. 4. DispensingState
8. 5. ReturningChangeState
9. 6. VendingMachine
10. Main
11. Output
12. Key Design Decisions

**Pattern → source-section citations:**

| Pattern (section 2) | Article section |
|---|---|
| State Pattern for lifecycle-heavy objects | Overview; What & Why the State Pattern?; Key Design Decisions |
| Uniform state interface | What & Why the State Pattern? |
| Fail fast on invalid actions | 2. IdleState |
| Explicit transition topology with conditional shortcut | What & Why the State Pattern? (state list); 3. MoneyInsertedState; 4. DispensingState |
| Shared context stored on the machine | 3. MoneyInsertedState; 6. VendingMachine; Key Design Decisions |
| Validate before committing to a transition | 3. MoneyInsertedState |
| One abstract product base class | 1. Item (Base Class + Subtypes); Key Design Decisions |
| Keyed map for inventory lookup | 6. VendingMachine; 4. DispensingState; Key Design Decisions |
| Separate selection from fulfillment | 3. MoneyInsertedState; 4. DispensingState; Key Design Decisions |

No quotes reproduced; all wording above is original.
