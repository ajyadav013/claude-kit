---
source: https://algomaster.io/learn/lld/sequence-diagram
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Sequence diagrams: modeling who calls whom, in what order, and who is blocked

## What it teaches
How to storyboard runtime interactions between objects and services on a
single time-ordered page. Where a use case diagram states a capability and a
class diagram lists the participants, the sequence diagram supplies the
missing middle: the exact ordering of calls and responses that realizes a
feature. The chapter builds up from the four structural elements (actors,
participants, lifelines, activation bars), catalogs six message arrow types,
and finishes with combined fragments that embed branching, looping, and
parallelism directly in the diagram.

## Key patterns & decisions
- Time flows downward: each actor or participant owns a dashed vertical
  lifeline; reading top to bottom is reading forward in time, and every arrow
  connects two lifelines at the moment the interaction happens.
- Actor/participant boundary mirrors the system boundary: the external
  initiator sits leftmost; internal components (controller, service, database)
  are the participants doing the work.
- Activation bars make blocking visible: a thin rectangle on a lifeline spans
  the interval a participant is actively processing; nested bars show a caller
  waiting on a callee, which no arrow by itself can convey.
- Synchronous vs asynchronous arrow semantics: a solid, filled-head arrow is a
  blocking call (phone-call model — the sender waits for the return); an
  open-head arrow is fire-and-forget (text-message model — publish an event,
  enqueue a job, move on, with no extended activation bar because nothing
  waits).
- Return messages as dashed arrows: optional per the standard but the chapter
  recommends always drawing them, because named returns make the diagram
  self-documenting about what data flows back.
- Self-messages, create, and destroy: a looped arrow marks a participant
  calling its own method; a participant created mid-flow appears at its
  creation point rather than at the top; an X terminates a lifeline to model
  cleanup such as session invalidation or releasing a resource.
- Combined fragments encode control flow inside the diagram: an alt frame
  holds mutually exclusive guarded branches (if/else), opt holds a single
  conditional block with no else, loop wraps a repeated interaction (one
  frame instead of arrows per iteration), and par splits a frame into
  sections that run concurrently.
- Debugging use case: production incident triage (did the order service call
  the gateway before or after reserving stock?) is exactly a
  sequence-ordering question, and the diagram makes such ordering bugs
  visible without reading code.

## When to apply / trade-offs
- Use when the interesting complexity is inter-component call ordering:
  authentication handshakes, checkout flows, event-driven fan-out, any
  cross-service trace. Skip it for purely static structure.
- Return arrows and activation bars add clutter but pay for themselves in
  larger diagrams; omitting returns saves ink at the cost of guessing what
  each callee hands back.
- The async arrow is the right notation whenever a queue or event bus sits
  between sender and receiver — drawing that as a synchronous call would
  falsely imply the sender blocks on delivery.
- Fragments keep diagrams honest about branching but nest poorly; deeply
  nested alt/loop frames are a signal the flow should be split into several
  smaller diagrams.

## Fidelity check
1. Claim: nested activation bars express a caller waiting on a callee.
   Support: the capture's login walkthrough shows the auth service's bar
   opening on receipt of the login call and containing a shorter database
   bar inside it, explicitly noting the service is idle-waiting while the
   database works.
2. Claim: asynchronous sends are drawn without a waiting period. Support: in
   the capture's example an order service publishes an event to a queue and
   proceeds immediately; the text points out the sender's activation bar does
   not extend because no response is awaited, and the queue later delivers to
   the notification service.
3. Claim: the par fragment models simultaneous post-order side effects.
   Support: the capture describes an order-placement frame split into three
   concurrent sections — sending a confirmation, recording an analytics
   event, and reserving inventory — stressing these are kicked off at once,
   possibly on separate threads or queues, not sequentially.
