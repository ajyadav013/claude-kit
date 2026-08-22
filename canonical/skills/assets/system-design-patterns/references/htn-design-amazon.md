# Digest: Design Amazon (HLD)

- **Source:** https://x.com/Harry_The_Nerd/status/2070543086258979132
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Consistency tiering per data class
The design assigns different consistency guarantees to different data: prices, stock counts, and
payment state get strong consistency; descriptions, reviews, and recommendation-style data can lag
(eventual consistency). Use this partitioning whenever a system mixes financial/contractual data
with presentation data — it lets the read-heavy 90% scale cheaply while the money-touching 10%
stays correct. Trade-off: two operational regimes (sync writes + cache invalidation vs. async
consumers) coexisting in one system.

### Read/write traffic classification at the API gateway
Beyond auth, rate limiting, and routing, the gateway classifies each request as read (browse,
search, product pages) or write (orders, inventory, payments) and sends each class to separate
service clusters with independent scaling policies. The point is blast-radius isolation: a
flash-sale write spike cannot starve browsing traffic. Cost: duplicated deployment surface and the
need to keep the classification rules current as APIs evolve.

### Presigned-URL media bypass
Binary payloads (seller product images/videos) never transit the gateway. After authentication the
seller obtains presigned object-storage URLs and uploads straight to S3. Keeps the gateway and app
tier out of the petabyte-scale media path. Trade-off: upload validation and quota enforcement move
to the storage layer and the post-upload pipeline.

### Event-driven media ingestion pipeline with fan-out consumers
Storage-bucket upload events flow into Kafka; a horizontally scaled transcoding pool produces image
variants (thumbnail/medium/full, WebP-compressed) and video renditions (360p/720p/1080p HLS
segments plus a preview frame), stored under a per-product/per-variant key layout. A completion
event then fans out to two independent consumers: one writes catalog metadata to the DB and warms
the cache, the other indexes the product into the search engine. Use when a single ingest must
feed multiple downstream stores; each consumer retries independently. The transcoding pool is the
listing-latency bottleneck and is scaled by adding workers.

### Semi-structured attribute column for heterogeneous catalogs
Product attributes vary wildly by category (a laptop's specs vs. a shirt's size/fabric), so
attributes live in a JSONB column instead of per-category tables. Gains schema flexibility across
350M products without table proliferation; loses some relational validation and indexed querying
(which is delegated to the search engine instead).

### Scatter-gather page assembly
A product page is composed from five parallel fetches — metadata (cache-first), media URLs (CDN
only, no backend), live inventory count, seller info, and top reviews — and rendered once all
return. The same parallel-fan-out idea reappears at checkout for per-item stock/price checks. Use
whenever page latency would otherwise be the sum of sequential service calls; the trade-off is that
tail latency becomes the max of the fan-out, so each leg needs its own cache/timeout discipline.

### Power-law-aware selective caching with an L1/L2/L3 hierarchy
Because roughly the top 1% of products drive about 90% of traffic, only hot items are cached
(longer TTLs); cold long-tail items go straight to the database with no cache overhead. For the
hottest flash-sale items a three-layer hierarchy applies: per-app-server in-memory LRU (L1), Redis
(L2), PostgreSQL (L3). This is the standard hot-key mitigation — full-catalog caching would blow
Redis memory at 350M products. Trade-off: staleness windows multiply across layers, so
invalidation (especially for price) must be explicit.

### Multi-signal search ranking over a search engine
Full-text search, faceted filters, and ranking run in Elasticsearch across the whole catalog.
Ranking blends text-match score with commercial signals: sales velocity, rating/review volume,
price competitiveness within category, membership-program eligibility, and stock status (out-of-
stock demoted). Price changes reindex immediately (trust risk); rating/count changes sync in
batches. Composite indexes on (category, price, rating, in-stock) keep faceted queries fast. Hot
query results get short-TTL Redis caching in front of the cluster.

### Sorted-set autocomplete
Type-ahead suggestions come from a Redis Sorted Set keyed by prefix, scored by historical search
frequency, read with a top-N reverse-range call — no search-engine involvement at keystroke time.
A background job rebuilds scores from query logs. Cheap sub-millisecond reads; the trade-off is
suggestion freshness bounded by the log-analysis cadence.

### Cache-primary store with async durable backup (cart)
The cart lives in a Redis hash keyed by user (all O(1) operations, one call reads the whole cart,
30-day TTL), and is asynchronously mirrored to PostgreSQL via a Kafka consumer. On Redis loss the
cart is rebuilt from the backup, accepting that the last few mutations may vanish — a deliberate
durability downgrade justified by the data's ephemeral nature. Use for high-churn, low-value-per-
write state; never for money.

### Deferred validation at the point of commitment
Price and stock are re-verified at checkout, not at add-to-cart, because both drift constantly
between the two moments. If either changed, the user is told before proceeding. Generalizes to:
validate expensive invariants at the latest moment they matter, not eagerly. Cost: a checkout-time
fan-out of per-item calls, mitigated by parallelism and a cart-size cap.

### Two-phase inventory reservation (reserve-then-confirm)
Placing an order reserves stock (an atomic decrement plus a reservation row with a ~15-minute TTL)
rather than permanently decrementing it. Payment success converts the reservation to a confirmed
sale in the source-of-truth DB; payment failure increments the count back; abandonment lets the TTL
auto-release. Prevents overselling without holding stock hostage to abandoned checkouts. The
reservation table carries an explicit status enum (reserved/confirmed/released) and expiry.

### Redis distributed lock with expiring ownership
Inventory mutation is guarded by a set-if-not-exists lock with a 5-second expiry — atomic
acquisition, and the TTL guarantees release even if the holder crashes, avoiding deadlock. The lock
is held only long enough to record the reservation. Adequate for normal contention (microsecond
hold times); it becomes the bottleneck for very hot items, which motivates the next pattern.

### Queue-based load leveling for write spikes
During a flash sale (up to 100k requests/second against one product) purchase requests are not
allowed to fight over the lock; they are appended to a per-product Kafka topic and a single worker
drains it sequentially, checking and decrementing stock one request at a time. Users get an
immediate "processing" acknowledgment and learn the outcome asynchronously via notifications.
Contention is eliminated by serialization; the trade-off is converting a synchronous purchase into
an async one, which the UX must absorb.

### Choreographed saga with compensating transactions
Order placement spans independent services (order, inventory, payment, warehouse, notification)
coordinated through Kafka events: order-created → inventory-reserved → payment-completed →
order-confirmed → warehouse-notified → user-notified, with shipping updates after. Any failure
publishes a failure event that triggers compensation — a payment failure releases the inventory
reservation, an inventory failure prevents payment from ever being attempted — so no partial order
state is permanent. Kafka durability lets each step retry from its offset without replaying the
whole flow; consumers carry idempotency keys so redelivery is harmless.

### Idempotency keys for exactly-once payment effect
Every charge request carries a unique key (derived from the order id), stored in Redis with a
24-hour TTL. A retried request with a seen key returns the original result instead of charging
again, making double-charge impossible under network retries. The external gateway (typically
0.5–2s per call) is the latency bottleneck, so charging is fully asynchronous behind Kafka — the
user never blocks on the gateway during checkout.

### Price snapshot at order time
Each order line stores the unit price paid, rather than referencing the live product row, so order
history remains truthful after later price changes. A small pattern with outsized
audit/compliance value; the cost is denormalization.

### Integrity-by-constraint for reviews
A uniqueness constraint on (product, user) enforces one review per buyer, and a foreign key to the
order row enforces verified-purchase-only reviews — both invariants pushed into the database rather
than application code. Aggregate rating and review count on the product row are denormalized
counters updated asynchronously by Kafka consumers (the same async-counter approach used for seller
ratings), then periodically synced to the search index.

### Transactional (non-coalesced) notifications
The notification service subscribes to every order-lifecycle event (confirmed, preparing, shipped,
out-for-delivery, delivered, payment-failed, out-of-stock) and delivers each individually over
push (APNs/FCM) and email. The explicit contrast: social feeds coalesce (500 likes → one alert),
but commerce events are transactional and each must arrive on its own. Choose coalescing vs.
individual delivery based on whether each event carries independent user obligation.

### Capacity-estimate-driven problem framing
The estimation section (50M DAU, 2–3% conversion → 1–1.5M orders/day, 350M products, ~1.75 PB
images + ~1.75 PB video, ~3.5 TB metadata, ~10 GB/day of order rows, 100k RPS flash-sale spikes)
is used to identify what actually matters: storage is dominated by write-once media, but the real
engineering problem is write consistency under coordinated purchase spikes — the inverse of
social platforms, where read-time feed generation dominates. The technique: run the numbers first,
then let the dominant term dictate where the design effort goes.

## Not absorbed

- Series branding ("High-Level Design Questions-Based Series #20") — interview-prep packaging, not
  engineering content.
- Closing sign-off ("That's all, folks…" style farewell) — social pleasantry.
- Engagement metrics in the capture (view/like/repost counts) — platform chrome, not article
  content.
- Repeated comparisons to the author's earlier Instagram/Twitter design posts (e.g. "same
  architecture as Instagram and Twitter" for notifications) — cross-promotion of the series; the
  one substantive contrast (coalesced vs. transactional notifications) is absorbed above.
- Named-vendor menu in the technology summary (Kong vs. AWS API Gateway, CloudFront vs. Akamai,
  Razorpay vs. Stripe) — brand enumeration; the role each component plays is already captured in
  the patterns.
- The out-of-scope list (recommendations ML, support chatbot, subscriptions, ads, returns,
  warehouse robotics) — scoping housekeeping for the exercise, no design content.

## Fidelity check

**Post count in capture:** 1 (a single long-form article post; `postCount: 1` in the JSON, no
`---AUTHOR-POST-BREAK---` separators present).

**Article outline (author's own numbered sections):**
1. Requirements (functional / out of scope / non-functional)
2. Capacity Estimation
3. API Gateway
4. User and Seller Profile Services
5. Product Catalog Service and Upload Pipeline
6. Search Service
7. Cart Service
8. Inventory Service
9. Order Service and Saga Pattern
10. Payment Service
11. Reviews and Ratings Service
12. Notification Service
13. Full Data Flow Summary
14. Resilience and Fault Tolerance
15. Technology Choices Summary

**Pattern → source-section mapping:**

| Pattern | Article section |
|---|---|
| Consistency tiering per data class | §1 Requirements (non-functional); reinforced in §4, §5, §11 |
| Read/write traffic classification at the gateway | §3 API Gateway |
| Presigned-URL media bypass | §3 API Gateway; §5 seller upload flow |
| Event-driven media ingestion pipeline with fan-out | §5 Product Catalog Service and Upload Pipeline |
| Semi-structured attribute column (JSONB) | §5 data model |
| Scatter-gather page assembly | §5 product page read path; §7 checkout validation; §13 read flow |
| Power-law selective caching + L1/L2/L3 | §5 caching strategy; §14 resilience |
| Multi-signal search ranking | §6 Search Service |
| Sorted-set autocomplete | §6 autocomplete subsection |
| Cache-primary store with async durable backup | §7 Cart Service |
| Deferred validation at point of commitment | §7 price/inventory validation at checkout |
| Two-phase inventory reservation | §8 reservation flow; §14 resilience |
| Redis distributed lock with expiring ownership | §8 distributed lock subsection |
| Queue-based load leveling for write spikes | §8 flash-sale subsection; §13 flash sale flow |
| Choreographed saga with compensating transactions | §9 Order Service and Saga Pattern; §14 |
| Idempotency keys for exactly-once payment effect | §10 Payment Service; §9 consumer idempotency; §14 |
| Price snapshot at order time | §9 OrderItems data model |
| Integrity-by-constraint for reviews | §11 Reviews and Ratings Service; §4 seller-rating counters |
| Transactional (non-coalesced) notifications | §12 Notification Service |
| Capacity-estimate-driven problem framing | §2 Capacity Estimation |
