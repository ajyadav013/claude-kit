---
source: https://blog.algomaster.io/p/system-design-top-15-trade-offs
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Fifteen recurring trade-off axes in system design

## What it teaches

A survey piece built on one thesis: every architectural choice buys one
property by paying for another, so design skill is really trade-off literacy.
It catalogs fifteen paired concepts that come up in nearly every design
discussion, each anchored by a concrete product scenario (banking, gaming,
social feeds, streaming) so the abstract axis maps to a felt consequence.

## Key patterns & decisions

- **Scalability vs performance are different questions**: one asks whether the
  system can absorb more total work, the other how fast a single task
  finishes; adding machines for growth can add coordination delay that hurts
  individual-request speed.
- **Vertical vs horizontal scaling**: grow one box (simple, hard ceiling,
  single point of failure) or add boxes (near-unbounded, distributed-systems
  complexity); startups typically graduate from the first to the second.
- **Latency vs throughput as separate targets**: interactive/real-time apps
  (gaming) optimize time-per-message; analytics pipelines optimize volume-over-
  time, and tuning for one rarely optimizes the other.
- **SQL vs NoSQL by workload shape**: relational stores win on structured
  data, rich queries, and transactional integrity (ledgers); non-relational
  stores win on flexible schemas and horizontal scale for high-volume
  semi-structured data (recommendation signals).
- **CAP as a two-of-three forcing function**: under partition, pick returning
  the freshest data (inventory decrement on checkout) or staying up
  (messaging that keeps flowing when some servers die).
- **Strong vs eventual consistency**: immediate global visibility of an update
  (account transfer) versus convergence after a lag (a photo propagating to
  followers' feeds) — pick per-feature, not per-system.
- **Read-through vs write-through caching**: lazy-load on miss suits
  read-heavy, rarely-updated data (product pages); synchronous dual-write
  suits correctness-sensitive writes (seat/ticket booking that must never
  oversell from a stale cache).
- **Batch vs stream processing**: accumulate-then-process for periodic bulk
  work (statement generation) alongside per-event processing for immediacy
  (fraud flags on live transactions) — the same company often runs both.
- **Sync vs async execution**: block-and-confirm when the user must know the
  outcome now (payment), background it when they don't (media upload
  continuing while the user scrolls).
- **Stateful vs stateless services**: remembered sessions give continuity
  (persistent shopping cart) at scaling cost; self-contained requests (typical
  REST APIs) scale trivially but push context onto every call.
- **Long polling vs WebSockets**: held-open request/response cycles for
  moderate-frequency updates (notifications) versus a persistent full-duplex
  channel for genuinely bidirectional real-time traffic (multiplayer games).
- **Normalization vs denormalization**: single-copy tables for integrity
  versus deliberate duplication for read speed (storing latest comments
  alongside the post row).
- **Monolith vs microservices as a lifecycle decision**: start unified for
  deployment simplicity, split into independently deployable services when
  team velocity and scaling pressure justify the operational overhead.
- **REST vs GraphQL**: many simple endpoints and over/under-fetching versus a
  single query surface with client-shaped responses at the cost of upfront
  schema design.
- **TCP vs UDP**: ordered, verified, retransmitted delivery (email) versus
  fire-and-forget speed where occasional loss is acceptable (live video,
  game state).

## When to apply / trade-offs

- Useful as a checklist when reviewing a design doc: for each axis, ask
  whether the choice was made deliberately or inherited by default.
- The list is breadth-first primer material — each entry is a paragraph, not
  an implementation guide; depth (consistency models, cache invalidation
  hazards) lives elsewhere.
- The framing "pick per user-experience requirement, not globally" is the
  transferable lesson: one product legitimately mixes both sides of most axes.

## Fidelity check

1. *Claim: the article's thesis is that design equals trade-off selection.*
   The capture opens by declaring trade-offs the first rule of system design
   and defines every include/exclude decision as one.
2. *Claim: the cache section pairs strategies with overselling risk.* The
   capture illustrates write-through caching with a movie-ticket booking
   system that records bookings in cache and database at the same moment to
   prevent overbooking, and read-through with product pages loaded into cache
   on first view.
3. *Claim: batch and stream processing coexist in one business.* The capture's
   example has credit-card companies doing daily billing/statements in batch
   while running real-time transaction analysis for fraud detection as a
   stream.
