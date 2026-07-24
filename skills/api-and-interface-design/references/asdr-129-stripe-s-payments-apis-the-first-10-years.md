---
source: https://stripe.com/blog/payment-api-design
author: Stripe (Michelle Bu)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Ten years of evolving a public payments API without breaking anyone

## What it teaches
A decade-long case study in public API evolution. Stripe's original card-only
abstractions (a client-side token plus a server-side charge) were built around
the simplest possible payment type: one that finalizes instantly and needs no
customer action. As they added ACH, Bitcoin, iDEAL, OXXO, and dozens more,
they kept bolting new states and one-off resources onto those primitives until
the integration required developers to juggle two divergent state machines
spanning client and server, with webhook handlers sitting in the critical path
of revenue. The lesson: the first abstraction you shipped is foundational
because it was first, not because it was right — and the outlier you optimized
for may actually be the special case (cards were the anomaly, not the norm).
The fix was a ground-up redesign (PaymentIntents + PaymentMethods) that split
"how to pay" (static credentials, stateless) from "the attempt to get paid"
(one server-owned state machine), plus a two-year migration strategy that
never forced anyone to rewrite everything at once.

## Key patterns & decisions
- **Product debt in APIs**: incremental parameters and states accrete like
  tech debt; users resist restructuring integrations, so the pressure is
  always toward bolting on rather than redesigning — until the concept count
  overwhelms them.
- **Classify the domain on orthogonal axes before designing**: Stripe mapped
  every payment method on a 2x2 (immediate vs. delayed finalization x customer
  action required vs. not) and discovered cards sat alone in one quadrant —
  the foundational abstraction had been modeled on the exception.
- **Separate the stateless "how" from the stateful "what"**: PaymentMethod
  carries only credentials/scheme info with no transaction state;
  PaymentIntent owns the money-movement lifecycle. One state machine, not two.
- **No terminal failure state — loop back for retry**: a failed attempt
  returns the intent to "needs a payment method," so the same server-created
  object supports repeated client-side retries with different instruments.
- **Keep webhooks out of the money-critical path**: the redesign made the
  only required webhook a post-success fulfillment signal, so a down consumer
  delays fulfillment instead of silently losing payments (the old
  source-then-charge flow refunded customers when the follow-up call never
  arrived — direct conversion loss).
- **Layer new APIs over legacy resources for migration**: every new-style
  payment still materializes a legacy charge object, so analytics/reporting
  integrations (often owned by other teams) keep working while the payment
  flow migrates independently.
- **Polymorphic typed sub-hash for per-variant data**: rather than letting a
  resource balloon (charge went from ~11 to 36 properties in seven years),
  method-specific details live under a discriminated, typed nested field —
  a pattern they later standardized across the API.
- **Progressive disclosure via explicit opt-out packaging**: a single,
  self-describing parameter (error on any required action) collapses the
  full state machine into a synchronous simple call for card-only startups —
  measurable, honest about its limits, and upgradeable by deleting one line
  rather than re-integrating.
- **Design-sprint mechanics for API redesign**: small team, months in a room,
  laptops closed, questions deferred between sessions, colors/shapes instead
  of premature names, hypothetical integration guides written for every real
  (and invented) payment method as the primary validation tool, fast
  reversible decisions over stasis.

## When to apply / trade-offs
- Apply the 2x2-classification and "which case is really the outlier" test
  whenever a v1 abstraction starts sprouting per-variant states or sibling
  resources; three special cases is the smell.
- The unified design deliberately made the simplest case harder (card-only
  users now face flipped call order and webhooks). Uniformity flattens the
  worst case but raises the floor — you must ship a packaging/preset for the
  eager 80% or they bounce. Two parallel incompatible integration guides,
  their first attempt, was worse than either option alone.
- Layering over legacy costs internal cleanliness (they kept a cluttered
  resource alive indefinitely) but buys migration without breakage; changing
  the semantics of an existing resource's state machine would break every
  consumer's assumptions.
- Budget for the unglamorous majority: rollout took ~2 years, mostly docs,
  support content, tutorials, CLI tooling, and dashboard work — not API code.

## Fidelity check
1. Claim: cards were the lone occupant of the "instant finalization, no
   customer action" quadrant. Capture support: the article's payment-method
   table shows cards alone in the top-left cell, with the explicit
   observation that global payment methods aren't the odd ones out — cards
   are.
2. Claim: the legacy flow could silently lose payments when connectivity
   dropped. Capture support: for iDEAL, if the browser died after the source
   became chargeable but before the server created the charge, Stripe
   refunded the customer's money hours later — described as a conversion
   nightmare — and the recommended mitigation (webhook-driven charge
   creation) itself failed if the user's app was down.
3. Claim: the simple packaging is a single explicit parameter rather than a
   separate API. Capture support: the "card payments without bank
   authentication" integration is implemented as an error-on-requires-action
   flag on the intent, chosen so usage is trackable and upgrading means
   removing the parameter and handling the action state.
