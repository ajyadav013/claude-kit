---
source: https://algomaster.io/learn/lld/use-case-diagram
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Use case diagrams: scoping a system by who can do what, before any design

## What it teaches
How to capture a system's scope from the outside-in, before touching classes
or schemas. A use case diagram is a UML behavioral diagram that answers a
single question — which external parties can achieve which goals with the
system — while deliberately saying nothing about implementation. The chapter
defines the four building blocks (actors, use cases, system boundary,
relationships), then walks a step-by-step construction of a movie-ticket
booking system's diagram.

## Key patterns & decisions
- Requirements-level abstraction on purpose: the diagram captures scope and
  user goals only; classes, data models, and mechanisms are explicitly out of
  frame, which keeps it usable right after requirements gathering and before
  detailed design.
- Primary vs secondary actor split: primary actors initiate interactions to
  pursue their own goal (customer, admin) and conventionally sit on the left;
  secondary actors (payment gateway, notifier) are invoked by the system to
  help complete a use case and sit on the right. External systems count as
  actors, not just humans.
- Three-rule test for a valid use case: it must be named with a leading verb,
  represent a complete goal rather than a single input step, and end with a
  meaningful result for the actor. Anything finer-grained belongs inside a
  use case description, not on the diagram.
- System boundary rectangle as a scope contract: everything inside the box is
  the team's responsibility to build; everything outside (all actors) is
  external. Drawing the box is literally drawing the scope line.
- Include for mandatory sub-flows: when a base use case can never complete
  without another one running (checkout always validates payment), the
  dependency is modeled as an include, arrow pointing from base to included.
- Extend for optional enhancements: when behavior is added only under some
  condition (applying a coupon during booking), it is modeled as an extend,
  with the arrow pointing from the extension back to the base, which works
  fine without it.
- Actor generalization: a specialized actor (admin as a kind of user) inherits
  every association of the parent and adds its own, avoiding duplicated lines.
- Five-step construction recipe: identify actors, list each actor's goals as
  use cases, draw the boundary, connect associations, then layer in include /
  extend / generalization last.

## When to apply / trade-offs
- Best used early — immediately after requirements, before design — as a
  shared map between engineers and non-technical stakeholders.
- In a design-interview setting the formal diagram is optional; the transfer
  lesson is that spending a few minutes enumerating actors and goals before
  class design demonstrates structure and reduces later rework.
- The granularity rules are the main failure mode: modeling individual UI
  steps as use cases produces an unreadable diagram, and unlabeled or wrongly
  directed include/extend arrows invert the meaning (include arrows point at
  the mandatory helper; extend arrows point back at the base).
- The diagram intentionally cannot express ordering, data, or error handling —
  pair it with sequence or activity diagrams for those.

## Fidelity check
1. Claim: secondary actors never start the interaction. Support: the capture
   describes a payment gateway that only acts when the system calls on it
   during checkout, contrasting it with goal-driven primary actors like a
   customer booking a ticket.
2. Claim: a use case must be a complete goal, not a step. Support: the
   capture contrasts booking a ticket (complete, ends with a confirmed
   booking) against entering a card number (one step inside a goal, too
   granular to appear on the diagram).
3. Claim: include and extend differ in necessity and arrow direction. Support:
   the capture's worked example makes payment an included (mandatory) part of
   booking because no booking exists without payment, while genre filtering
   extends browsing as an optional add-on, with the extend arrow drawn from
   the extension toward the base use case.
