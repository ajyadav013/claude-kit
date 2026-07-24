---
source: https://algomaster.io/learn/lld/state-machine-diagram
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Modeling object lifecycles with UML state machine diagrams

## What it teaches

A state machine diagram captures how a single object's behavior changes over its
lifetime: which conditions (states) it can occupy, which events move it between
those conditions, and what work happens on each move. It deliberately contrasts
with an activity diagram — the question is not "what steps run in what order"
but "given the object's current condition, which operations are even legal."
The chapter argues that some domain objects (orders, vending machines,
elevators, user accounts) are fundamentally state-driven, and for those objects
a lifecycle picture is more valuable than a class hierarchy.

The core vocabulary: states drawn as rounded rectangles named with nouns or
adjectives (never verbs); exactly one initial pseudo-state (a filled dot) with
a single unlabeled outgoing arrow; optional terminal states (bullseye symbol)
that only make sense for objects whose lifecycle genuinely ends; transitions as
event-labeled arrows; guard conditions in square brackets that disambiguate two
transitions fired by the same event; and slash-suffixed actions that run during
a transition. States may also declare entry, ongoing (do), and exit behaviors.
Events themselves come in four flavors — external signals, method-call events,
time-based events (timeouts), and condition-became-true events.

Beyond simple states, the notation offers composite (nested) states where an
outer state contains its own sub-lifecycle and an outer transition exits from
any inner sub-state at once; self-transitions where an event is handled by
looping back into the same state (re-triggering exit/entry behavior); and a
diamond-shaped choice pseudo-state that routes to one of several targets based
on a runtime value rather than a binary guard.

Finally the chapter gives a six-step recipe: pick exactly one object, enumerate
its conditions, mark start and end, define event-driven transitions per state,
add guards where one event can land in different targets, then audit the
diagram for orphan states and unhandled events.

## Key patterns & decisions

- Model one object per diagram — lifecycle diagrams lose value when they try to cover a whole system.
- States are nouns/adjectives, events are camelCase verbs — the naming split keeps "condition" and "trigger" visually distinct.
- Guard conditions in brackets resolve ambiguity when one event can lead to multiple targets; without them the diagram is nondeterministic.
- Composite states factor shared exits: a policy-violation transition drawn from the outer state applies regardless of which sub-state the object is in.
- Self-transitions model "handle the event, stay put" behavior (add money to an existing balance, receive a chat message while connected) and re-fire entry/exit actions.
- Missing-transition audit as a design review: every non-terminal state needs an outgoing arrow per relevant event, and gaps on the diagram expose edge cases (payment-gateway timeout, stock exhausted mid-purchase) that hide in prose specs.
- Diagram-to-code mapping: states become an enum, transitions become a transition method, guards become conditional checks — making this the most directly implementable UML diagram.
- Choice pseudo-state for multi-way runtime branching, when the destination depends on a computed value rather than a yes/no guard.

## When to apply / trade-offs

Reach for a state diagram when an object's valid operations depend on its
current condition — order fulfillment, payment flows, device controllers,
account status. Skip it for objects that are mostly data with no meaningful
lifecycle, and don't force a final state onto perpetual systems (an elevator
never terminates). The main cost is diagram sprawl; composite states are the
tool for keeping hierarchy readable instead of drawing every combination flat.
The validation step (every state reachable, every event accounted for) is
where most of the payoff lives — it converts implicit assumptions into visible
gaps before code exists.

## Fidelity check

1. Claim: guards exist to disambiguate same-event transitions. Support: the capture's vending-machine example shows two arrows out of one state both triggered by product selection, with an in-stock check deciding whether the machine dispenses or refunds.
2. Claim: composite states let an outer transition apply to all sub-states. Support: the capture's account example nests Standard and Premium inside Active, and a policy violation moves the account from Active to Suspended no matter which sub-state it occupied.
3. Claim: the notation mandates exactly one initial pseudo-state whose outgoing arrow carries no event label. Support: the capture states every diagram has one filled-dot start with no incoming arrows and a single unlabeled outgoing transition, because nothing "triggers" object creation.
