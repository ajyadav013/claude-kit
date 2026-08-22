---
source: https://algomaster.io/learn/lld/mediator
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Mediator: replace a many-to-many object web with a single coordinator

## What it teaches

When several peer objects (the running example is a login form: two text
inputs, a submit button, a status label) all need to react to each other's
state changes, the naive design gives every object direct references to its
peers. That produces an N-to-N dependency graph: each new widget multiplies
the wiring, coordination logic gets smeared across every class, components
stop being reusable outside this exact form, and any behavior change ripples
through multiple files. The Mediator pattern collapses that mesh into a star:
components report "I changed" to one coordinator object, and only that
coordinator knows the rules for how everyone else should respond.

The chapter's analogy is an airport control tower — aircraft never negotiate
with each other about landing order; each one talks only to the tower, which
holds the full picture and issues instructions. Adding or removing a plane
changes nothing for the other planes.

## Key patterns & decisions

- **Mediator as coordination hub**: interaction rules between peers live in
  exactly one class; peers hold a reference only to the mediator, never to
  each other, so the topology is a star instead of a mesh.
- **Narrow notification interface**: the mediator contract should be a single
  "something changed, here is who I am" callback; the mediator inspects the
  sender's identity and state to decide what to do, rather than exposing many
  specialized methods.
- **Deliberate coupling concentration**: the concrete mediator is *allowed*
  to know every concrete component type — the pattern intentionally absorbs
  all the coupling into one place, on the argument that one class knowing
  everyone beats everyone knowing everyone.
- **Abstract component base**: peers share a small base holding the mediator
  reference plus a notify helper, giving every component a uniform way to
  report changes.
- **Mediator vs Observer distinction**: an observer subject broadcasts the
  same event to all subscribers and lets each decide; a mediator actively
  routes and shapes the interaction (e.g., a chat room delivering a message
  to every member *except* the sender). Coordination logic vs blind fan-out.
- **Open-set membership**: participants can be registered or dropped at
  runtime (chat-room example) without any existing participant changing.

## When to apply / trade-offs

Apply when a cluster of objects is tightly interdependent — UI forms whose
controls enable/disable each other, chat-style hubs, any place where a change
in one participant should trigger tailored reactions in several others. The
win is reusable, self-contained components and one testable place for the
interaction rules. The cost is that the mediator itself can grow into a
god-object that concentrates complexity; the pattern trades distributed
coupling for one heavyweight class, which is only a net gain if the peer web
was genuinely tangled. For simple one-way broadcast, Observer is the lighter
tool.

## Fidelity check

1. *Claim: the naive design's flaw is peers holding direct references to
   peers.* The capture's problem section shows text fields knowing the
   button and the button knowing the fields and the label, and lists tight
   coupling, non-reusability, poor maintainability, and coordination logic
   scattered across components as the resulting failures.
2. *Claim: the mediator interface should be a single change-notification
   method.* The capture's class-diagram notes state that one
   component-changed style method is almost always enough, with the mediator
   working out the response from the sender's identity and state.
3. *Claim: the chapter differentiates Mediator from Observer via active
   routing.* Its chat-room section explicitly contrasts the two: the chat
   room decides who receives each message (everyone but the sender) and in
   what form, which it frames as coordinating rather than broadcasting.
