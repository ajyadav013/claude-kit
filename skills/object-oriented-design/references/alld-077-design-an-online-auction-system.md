---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/online-auction-system.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for an online auction and bidding platform

## What it teaches

The problem models an eBay-style marketplace: registered users list items
with a starting price and a fixed auction duration, other users discover
listings via search (name, category, price band) and place bids while the
auction is live. The system must keep the "current highest bid" authoritative
under concurrent bidding, push notifications to bidders when they are outbid,
and deterministically close the auction when its clock runs out, crowning the
top bidder. Extensibility for future features is an explicit requirement, so
the design leans on clear entity boundaries rather than clever coupling.

The reference decomposition:

- A user entity with identity fields — both sellers and bidders are the same
  type, differentiated only by their role relative to a listing.
- An auction-status enum capturing the listing lifecycle (active vs closed) —
  a minimal state machine that gates whether bids are accepted.
- An auction-listing entity that aggregates the item description, starting
  price, duration, the seller, the running highest bid, and the full bid
  history. The listing is the concurrency hot spot: many bidders mutate it
  simultaneously.
- A bid value object recording who bid, how much, and when — the timestamp
  matters for tie-breaking and audit.
- A singleton auction-service class holding the listing registry and exposing
  register/create/search/bid operations. Thread safety comes from concurrent
  collections: a concurrent hash map for the listing registry and a
  copy-on-write list for bid histories.
- A demo entry point separate from the service.

## Key patterns & decisions

- Lifecycle enum as a guard: bid acceptance is conditioned on the listing
  being in the active state, so closing an auction is a state flip rather
  than scattered timing checks.
- Bid history as an append-only, timestamped log kept alongside a cached
  "current highest" — reads of the winning bid are O(1) while the full
  history remains available for audit and notification.
- Copy-on-write collection for the bid list: optimizes for many readers and
  comparatively rare writes, giving iteration safety during concurrent bids
  without explicit locking.
- Concurrent map for the listing registry so listing creation and lookup
  interleave safely with bidding traffic.
- Observer-style outbid notification: the requirements make the system push
  updates to affected bidders whenever the highest bid changes, implying the
  listing (or service) notifies interested parties on state change.
- Time-boxed termination: the auction ends by duration expiry, and winner
  selection is derived from the recorded bids rather than a separate mutable
  field that could drift.
- Singleton service as the single writer coordination point for all
  listings.

## When to apply / trade-offs

The pattern set applies to any competitive-write domain: flash sales,
ticketing, order books. The core lesson is separating the durable event log
(all bids) from the derived hot value (current high bid) — the log gives you
audit and recovery, the cache gives you cheap reads, and the two must be
updated atomically or the listing lies to bidders. Copy-on-write bid lists
are elegant for read-heavy access but each write copies the whole list, so
they degrade under genuinely hot bidding — a production system would move to
per-listing locking or optimistic compare-and-swap on the high bid.
Duration-based closing done inside a single process (as here) needs a
scheduler or lazy check-on-access; a distributed version needs an external
timer authority. As with the other problems in this repo, this page is a
design skeleton — entities, responsibilities, and concurrency choices — with
runnable code only in the linked per-language solution folders.

## Fidelity check

1. Claim: the system must auto-update the highest bid and inform bidders of
   changes. Support: the requirements say the current highest bid is
   automatically updated and bidders are notified accordingly.
2. Claim: thread safety is achieved via concurrent hash maps plus
   copy-on-write lists. Support: the class inventory states the auction
   service uses those two concurrent collection types to protect listing
   access.
3. Claim: the auction closes on duration expiry with the top bidder declared
   winner. Support: the requirements specify the auction ends when the set
   duration is reached and the highest bidder wins.
