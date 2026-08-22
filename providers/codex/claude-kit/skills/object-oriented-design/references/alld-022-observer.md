---
source: https://algomaster.io/learn/lld/observer
author: algomaster.io (AlgoMaster)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Observer: one-to-many change notification with loose coupling

## What it teaches

The chapter builds the Observer behavioral pattern around a fitness-tracker
app whose central data object receives a continuous stream of metrics (steps,
active minutes, calories) from a wearable, while several modules — a live
dashboard, a persistence logger, a milestone alerter — must all react to each
update. The naive design has the data object construct and directly invoke
every dependent module. The chapter enumerates five distinct failure modes of
that arrangement: hard coupling to concrete dependent types; an Open/Closed
violation because every new consumer requires editing the data class;
inability to attach or detach consumers at runtime (e.g., when a user turns
off notifications); responsibility bloat, since a metrics container ends up
owning UI, storage, and alerting concerns; and a scalability chokepoint where
one ever-growing notification method becomes a merge magnet for every
feature team.

The pattern's remedy is a subscription list typed to an interface. A subject
interface exposes register/remove/notify operations; an observer interface
exposes a single update callback. The concrete subject keeps a list of
observer-interface references and walks it on every state change; concrete
observers each decide privately what a change means to them. The chapter uses
a pull flavor: on notification, each observer reaches back into the subject
through getters for whichever fields it cares about, which keeps the callback
signature stable as the subject grows new fields. The newspaper-subscription
analogy carries the intuition — the publisher delivers identically to every
subscriber and neither knows nor cares what each does with the paper.

Two extension exercises drive the payoff home: a weekly-summary feature is
added purely by writing one new observer class and registering it, and a
second domain (a stock exchange feeding a price display, a threshold alerter,
and a trading bot) shows the identical structure transplanted.

## Key patterns & decisions

- **Subscription list typed to an interface**: the subject depends only on
  the observer contract, dropping its knowledge of concrete consumers from
  several to zero.
- **Pull-style updates for interface stability**: observers fetch what they
  need from the subject after being poked, so adding subject fields never
  breaks the callback signature.
- **Runtime attach/detach as a first-class feature**: user settings or
  feature flags can add and remove listeners live; a removed observer simply
  stops receiving future broadcasts.
- **Single-responsibility restoration**: the subject returns to managing its
  own state only; reaction logic lives entirely in the observers.
- **Extension-by-registration**: new consumers are one new class plus one
  registration call, with zero edits to the subject or to sibling observers.
- **Observer-side testability**: each consumer can be unit-tested by driving
  its update callback directly against a stubbed subject.
- **Notification-method-as-merge-magnet smell**: a central "state changed"
  method that every new feature must edit is the signal to invert to
  publish/subscribe.

## When to apply / trade-offs

Use Observer when several parts of a system must react to changes in one
component, when the set of reactors varies at runtime, or when the publisher
should not know its audience. The pull style traded here has its own cost the
chapter leaves implicit: observers become coupled to the subject's getter
surface, and synchronous iteration means one slow or throwing observer can
delay the rest — concerns that push real systems toward event buses or async
dispatch at larger scale. For a fixed pair of collaborators, a direct call is
still simpler.

## Fidelity check

1. *Claim:* The naive design fails in five enumerated ways. *Support:* The
   capture lists tight coupling, Open/Closed violation, static/inflexible
   wiring, responsibility bloat, and a scalability bottleneck in the
   ever-lengthening notification method.
2. *Claim:* The refactor takes the subject's knowledge of concrete modules
   to zero. *Support:* The capture states the refactored data class no longer
   imports, creates, or references any concrete observer — it went from
   knowing three specific modules to knowing none.
3. *Claim:* The chapter demonstrates pull-based data access. *Support:* The
   workflow description says each notified observer retrieves the data it
   needs from the subject via getter methods, and the observer-interface step
   notes this keeps the interface stable as the subject gains new fields.
