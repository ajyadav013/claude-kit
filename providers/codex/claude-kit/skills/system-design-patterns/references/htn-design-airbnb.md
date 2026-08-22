# Digest: Design Airbnb (HLD)

- **Source:** https://x.com/Harry_The_Nerd/status/2079561027788611975
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

The article walks through a marketplace-booking architecture whose central thesis is that the
hard problem is not scale but *correctness under concurrent writes*: two guests must never end
up holding the same property for overlapping nights. Almost every design choice in the
availability/booking path flows from that invariant.

## Patterns

### Calendar-table availability model (one row per property per night)
Availability is materialized as a row keyed by `(property_id, date)`, with a status enum
(available / reserved / booked / blocked), a per-date price, and an optional booking reference.
A multi-night stay becomes N rows sharing one booking id. **When to use:** any date-range
inventory problem (lodging, rentals, appointment slots) where you need atomic range reservation
and per-unit-of-time pricing. **Trade-offs:** row count explodes (7M properties x 365 days ≈ 2.5B
rows in this estimate), but the composite primary key turns range checks into index scans, and
per-date rows give you host-blocked dates and weekend/event pricing for free. Checking a 5-night
window reduces to counting available rows in the range and comparing the count to the number of
nights requested.

### Pessimistic row locking for double-booking prevention
The authoritative reservation path uses the relational database's own row locks
(`SELECT ... FOR UPDATE` over the requested date rows) so that check-then-reserve is a single
serialized transaction. Competing transactions on the same rows block until the winner commits;
at most one booking can claim a given range. **When to use:** when the inventory truth already
lives in the RDBMS and check+update must be atomic — the article explicitly contrasts this with
reaching for a separate distributed lock (e.g., Redis-based, as in a typical e-commerce design):
if the data is in Postgres, native transactional locking is simpler and strictly correct.
**Trade-off:** the lock is a throughput bottleneck on hot properties (the article's example:
a popular beach destination at New Year with hundreds of concurrent attempts), which motivates
the next two patterns.

### Two-phase booking with expiring holds
To avoid holding a database lock while a human types card details, booking splits into:
(1) a millisecond-scale locked transaction that flips the dates to a `reserved` state with a
10-minute expiry timestamp, then commits; (2) after asynchronous payment succeeds, a second
transition from reserved to booked. A background expiry worker sweeps every ~60 seconds and
returns lapsed holds to available. **When to use:** any reserve-then-pay funnel where the
external step (payment, human confirmation) takes far longer than the consistency-critical step.
**Trade-offs:** inventory is temporarily withheld from other buyers during the hold window, and
you now need the sweeper as a safety net — but lock hold time drops from minutes to milliseconds.

### Redis bitmap fast path for availability filtering
For search (read) traffic, exact per-date truth is overkill. Each property gets one bitmap per
month (one bit per day, so a month fits in ~4 bytes); date-range availability across candidates
is a bitwise AND, sub-millisecond, batched with MGET. **When to use:** separating a
high-QPS approximate read path from a low-QPS authoritative locked write path. **Trade-off:**
the bitmap can be slightly stale; that is acceptable precisely because the final booking attempt
re-checks under the database lock. Search never touches the locked tables at all.

### Layered search funnel (coarse index → fast-path filter → cache hydration)
A search like "location, date range, guest count, price cap" executes as: (1) Elasticsearch
query combining a native geo-radius filter (geo_point), price/rating/amenity filters, and a
coarse month-granularity availability field, returning ~hundreds of candidate ids; (2) Redis
bitmap AND to drop candidates unavailable for the exact dates; (3) batched Redis metadata
hydration for display (DB fallback on miss); (4) the same geo query also feeds the map view,
returning coordinates instead of ranked cards. **When to use:** queries that combine geo,
attribute filtering, and time-based inventory — one engine rarely does all three well, so each
layer cheaply prunes for the next. **Trade-off:** more moving parts and sync pipelines, but
p99 latency stays low (the stated target is search under 200ms including geo and availability).

### Geohash column alongside a search engine
Listings carry a precision-6 geohash (~1km cells) computed from lat/long, so prefix-similar
values imply physical proximity. Here Elasticsearch's geo_distance does the heavy lifting, but
the geohash column keeps cheap proximity grouping available in SQL. **Trade-off noted by the
author:** a pure geo store (like Redis GEO in a dating-app design) can't also do rich attribute
filtering and ranking in one query — hence Elasticsearch when filters are multi-dimensional.

### Saga orchestration with compensating transactions for booking
The booking flow is an event-driven saga over Kafka: initiate → reserve availability → charge
payment → confirm, with an explicit state machine (initiated, reserved, payment-processing,
confirmed, cancelled-by-either-side, completed, expired). Every failure edge has a compensation:
payment failure or timeout releases the reserved dates; unavailability expires the booking.
Kafka durability lets each step retry from its offset if a downstream service is briefly down.
**When to use:** multi-service workflows where a distributed transaction is impossible but you
must never strand partial state (dates held with no payment). **Trade-off:** eventual, not
immediate, consistency between services — mitigated by making every step idempotent and
compensable.

### Idempotency keys on bookings and payments
Both the bookings and payments tables carry a unique idempotency key so a double-click or
network retry replays the original result instead of creating a duplicate booking or a second
charge. Payment also checks the key in Redis before hitting the gateway. **When to use:** every
money-touching or state-creating endpoint that clients may retry. Essentially free insurance.

### Async payment with immediate "processing" state
External gateway calls (0.5–2s latency) are pushed behind Kafka; the client immediately sees a
processing status rather than blocking on the gateway round trip. Success/failure events then
drive the saga forward or trigger compensation. **Trade-off:** UI must handle an in-flight state,
but tail latency and gateway flakiness stop coupling to the booking transaction.

### Escrow-style delayed payout
Guest money is captured at booking but only released to the host 24 hours after check-in, and
held longer if the guest reports a problem in that window. This is a trust mechanism encoded in
the payment schema (a payout-after timestamp, separate gross / platform-fee / host-payout
amounts, payout states in the enum). **When to use:** two-sided marketplaces where the platform
mediates trust between strangers; the delay window is the dispute buffer.

### Double-blind dual reviews with deferred publication
Both sides review each other after a stay; nothing is visible until both have submitted or a
14-day clock runs out, enforced by an is-published flag plus a background publisher — not by
application goodwill. A uniqueness constraint on (booking, reviewer-role) caps reviews at one per
side per stay. Rating aggregates on user and property rows are denormalized counters updated
asynchronously off the publication event. **When to use:** any mutual-rating system where seeing
the counterpart's review first would bias or enable retaliation.

### Single user table for a two-sided marketplace
Hosts and guests share one users table with a host flag and *separate* rating/review-count pairs
per role, because one person is routinely both. Sensitive payout bank details live in a separate,
encrypted, strongly consistent table. **Trade-off:** role-specific columns on a shared row vs.
the join cost and identity-duplication risk of separate host/guest tables.

### Amenities as indexed rows, not a JSON blob
Filterable attributes are one row per (property, amenity) so conjunctive filters ("pool AND
parking") are ordinary indexed WHERE clauses. **When to use:** whenever an attribute set must be
queried, not just displayed; JSON arrays make conjunctive filtering slow and index-hostile.

### Presigned-URL direct-to-storage media upload
Photo uploads authenticate through the gateway but the bytes go straight to object storage via
presigned URLs; storage events fan out through Kafka to a worker that renders thumbnail/medium/
full variants, all served through a CDN. **Rationale:** large binaries should never transit the
API tier; listing photos change rarely, so edge cache hit rates are very high.

### Event-driven search-index synchronization
Listing create/update events flow through Kafka to an indexing worker that updates
Elasticsearch; the coarse availability field is refreshed by a nightly scan; rating fields sync
on review publication. **Trade-off accepted explicitly:** search can show a just-fully-booked
property for a few minutes — harmless because the bitmap filter and the final database lock
still prevent any incorrect booking. Consistency is spent only where the invariant demands it.

### Capacity anchors (restated as facts)
10M DAU; 7M active listings; 50M searches/day vs ~500K bookings/day (~1% conversion); ~20 photos
x 1MB per listing → roughly 140TB of images; ~2.5B calendar rows; hot listings can see hundreds
of simultaneous booking attempts. The skew between read volume (search) and consistency-critical
write volume (booking) is what justifies the split fast-path/authoritative-path architecture.

## Not absorbed

- Series branding ("Questions-Based Series #22") and the closing like/share/repost call to
  action — engagement framing, no engineering content.
- Repeated "same pattern as previous design" pointers (Amazon, Tinder, Instagram, "all nine
  systems") — series continuity glue; where a comparison carried a real trade-off (Postgres lock
  vs Redis lock, ES geo vs Redis GEO) the substance is captured above.
- The explicit out-of-scope list (Experiences, ML pricing, identity verification, superhost
  program, dispute resolution) — scoping for interview format, not design content.
- View/like/reply counts and timestamp — platform metadata.

## Fidelity check

- **Post count in capture:** 1 (a single long-form article post; `postCount: 1` in the JSON,
  no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline as authored (numbered sections):**
  1. Requirements
  2. Capacity Estimation
  3. API Gateway
  4. Host and Guest Profile Service
  5. Property Listing Service and Upload Pipeline
  6. Availability Service
  7. Search Service
  8. Booking Service
  9. Payment Service
  10. Reviews Service
  11. Notification Service
  12. Full Data Flow Summary
  13. Resilience and Fault Tolerance
  14. Technology Choices Summary
- **Pattern → source section mapping:**
  - Calendar-table availability model — §6 Availability Service
  - Pessimistic row locking — §6 Availability Service (reinforced in §13)
  - Two-phase booking with expiring holds — §6 Availability Service (expiry flow also in §12)
  - Redis bitmap fast path — §6 Availability Service (used again in §7)
  - Layered search funnel — §7 Search Service (flow recap in §12)
  - Geohash column alongside a search engine — §5 Property Listing Service (geohash column) and §7 (engine choice)
  - Saga orchestration with compensating transactions — §8 Booking Service (recap in §12/§13)
  - Idempotency keys — §8 Booking Service and §9 Payment Service
  - Async payment with processing state — §9 Payment Service
  - Escrow-style delayed payout — §9 Payment Service (timing also in §8 step 6)
  - Double-blind dual reviews — §10 Reviews Service (flow in §12)
  - Single user table for two-sided marketplace — §4 Host and Guest Profile Service
  - Amenities as indexed rows — §5 Property Listing Service
  - Presigned-URL direct upload — §3 API Gateway and §5 upload pipeline
  - Event-driven search-index sync — §5 (indexing) and §7 (sync + staleness trade-off, also §13)
  - Capacity anchors — §2 Capacity Estimation
