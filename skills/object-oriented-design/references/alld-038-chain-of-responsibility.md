---
source: https://algomaster.io/learn/lld/chain-of-responsibility
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Chain of Responsibility: composable handler pipelines instead of monolithic if-else

## What it teaches

The motivating problem is server-side request preprocessing: before business
logic runs, an HTTP request must clear authentication, authorization, rate
limiting, and payload validation. Cramming all of that into one processor
class as a ladder of conditionals fails on four axes — every new concern
(logging, caching, metrics) means editing the existing class; one method owns
five unrelated responsibilities; none of the checks can be reused by another
service without copy-paste; and per-environment variation (skip auth for
public routes, relax validation in dev) piles on yet more branching.

Chain of Responsibility restructures this as a linked pipeline of
single-purpose handlers. Each handler runs its one check and then chooses:
stop the chain (reject/handle), forward to the next handler, or do its work
*and* forward. The sender only knows the head of the chain; which handler
ultimately settles the request is invisible to it. The customer-support
analogy: a caller talks to tier-1, who resolves or escalates to tier-2, and
so on — the caller never picks the resolver.

## Key patterns & decisions

- **One handler, one concern**: each pipeline stage is its own class doing a
  single check, independently testable and reusable across services.
- **Sender/receiver decoupling via chain head**: the client wires handlers
  together in order and submits to the first one only; it never learns which
  stage handled or rejected the request.
- **Abstract base handler for link plumbing**: the set-next and forwarding
  mechanics live once in a shared base class so concrete handlers implement
  only their own decision logic.
- **Short-circuit semantics**: any stage can terminate processing (failed
  auth stops everything downstream), giving guard-style filtering for free.
- **Runtime-composable ordering**: because chains are assembled by linking
  objects, stages can be added, dropped, or reordered per deployment or
  environment without modifying any handler — the Open/Closed fix for the
  if-else ladder.
- **Two chain variants — filter vs contribute**: middleware-style chains
  pass-or-reject; the ATM cash-dispenser example shows the alternative where
  every stage always processes *and* forwards, each denomination handler
  taking its share of the amount and passing the remainder on.
- **Handle chain exhaustion explicitly**: the ATM example ends with an
  amount no handler can serve ($5 below the smallest note), teaching that a
  request can fall off the end of the chain and the residual must be checked
  rather than assumed to be zero.

## When to apply / trade-offs

This is the textbook shape for middleware stacks, interceptor pipelines,
approval/escalation flows, and staged validation — any place a request must
traverse an open-ended, reorderable series of gates. Prefer it over
conditionals when the set of steps changes over time or varies by context.
Costs implied by the design: no compile-time guarantee that *any* handler
handles a request (the exhaustion case), behavior depends on wiring order
established at assembly time, and tracing a request now means walking a
chain rather than reading one method top to bottom.

## Fidelity check

1. *Claim: the naive monolith fails Open/Closed and SRP.* The capture's
   breakdown section says adding checks like logging or metrics forces edits
   to the existing processor class, and that one method mixing auth,
   authz, rate limiting, and validation violates single responsibility.
2. *Claim: a handler has three possible outcomes.* The capture enumerates
   exactly these options: handle and stop, pass along, or handle and then
   pass along.
3. *Claim: the pattern also supports collaborative "everyone contributes"
   chains, with a residual to check.* The capture's ATM example has each
   denomination handler dispensing what it can and forwarding the rest, and
   notes a $275 withdrawal leaves $5 unserved because no handler covers
   denominations under $10 — a real system must detect that remainder.
