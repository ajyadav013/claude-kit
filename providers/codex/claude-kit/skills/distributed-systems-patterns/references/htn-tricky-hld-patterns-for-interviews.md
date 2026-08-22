# Digest: Tricky HLD Patterns for Interviews

- **Source:** https://x.com/Harry_The_Nerd/status/2056739488114856226
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Write-behind (write-back) caching

**What it is.** Writes land in a fast in-memory layer (Redis/Memcached-class store) and the caller gets an immediate acknowledgment; a background flusher later persists the accumulated data to the database in batches, so the DB never sees per-request write traffic.

**When to use.** High-frequency, loss-tolerant write streams: engagement counters (likes, views, impressions), analytics events, log ingestion. The article's illustration is a social platform accumulating story-view counts in memory rather than issuing a DB update per view.

**Trade-offs.** Big wins on write latency, DB load, and burst absorption via batching. The costs: a cache-node crash loses anything not yet flushed, consistency is only eventual, and you must build retry/recovery machinery for the flush path.

### Thundering-herd mitigation

**What it is.** Not a pattern to adopt but a failure mode to defend against: when a hot cache entry expires (or a service restarts, or clients reconnect en masse), every concurrent reader misses simultaneously and stampedes the backing store — the article's scenario is a product page cached for 30 minutes whose expiry sends thousands of identical queries to the database at once, spiking CPU and latency.

**When to use.** Any cache in front of an expensive recomputation or a shared datastore, especially with correlated expiry or flash-sale-style traffic.

**Mitigations covered.** (1) Request coalescing — one in-flight rebuild, everyone else waits on it; (2) a distributed lock (Redis- or ZooKeeper-based) so exactly one process recomputes; (3) jittered/randomized TTLs so entries don't expire in lockstep; (4) stale-while-revalidate — keep serving the old value while a background refresh runs; (5) rate limiting as a backstop for downstream systems. Payoff is stability and availability under spikes; cost is added coordination logic.

### Distributed transactions via two-phase commit (2PC)

**What it is.** A coordinator-driven protocol making a multi-service operation atomic. Phase one (prepare): the coordinator polls every participant, which validates the work, locks its resources, and votes yes/no. Phase two: a unanimous yes triggers a global commit; any no triggers a global rollback.

**When to use.** When partial success is unacceptable — the canonical case is a funds transfer where the debit and the credit must both apply or neither does; traditional banking/financial platforms still lean on this class of mechanism.

**Trade-offs.** You get strong consistency and cross-service atomicity, but pay with blocking behavior while locks are held, added latency, a coordinator that is both bottleneck and single point of failure, poor scalability, and messy recovery cases. The article notes most modern systems prefer sagas, event-driven flows, compensating transactions, and eventual consistency instead.

### Materialized views

**What it is.** Precompute an expensive query (joins, aggregations) on a schedule or in response to events, store the result as its own table/dataset, and serve reads from that instead of recomputing per request.

**When to use.** Read paths dominated by heavy aggregation: analytics dashboards, sales/usage reports, recommendation summaries, warehousing. The article's example: video-platform creator dashboards aggregate views/watch-time periodically rather than computing them live per page load.

**Trade-offs.** Reads become cheap and the DB sheds CPU, but data is stale between refreshes, you carry extra storage, and refresh orchestration is real complexity. Three refresh strategies are laid out: scheduled (every N minutes/hours), incremental (recompute only deltas), and event-driven (update on relevant writes).

### Bulk (batch) processing

**What it is.** Amortize per-operation overhead — connection setup, transaction bookkeeping, fsync, network round-trips — by grouping many small operations into one larger one, e.g. inserting 10,000 rows as batched statements instead of individual inserts.

**When to use.** ETL and ingestion pipelines, notification/email dispatch, logging, analytics. Cited real-world instances: bulk mailers, Kafka consumers polling messages in batches for throughput, and banks settling payments in grouped runs.

**Trade-offs.** Throughput and infrastructure efficiency go up sharply, but individual items wait longer (latency for the tail of a batch), a partially failed batch needs careful retry semantics, and batch size itself becomes a tuning knob.

### Read-replica architecture

**What it is.** One primary handles all mutations (insert/update/delete); asynchronous replication fans the data out to replica copies that serve selects, search, reporting, and analytics reads.

**When to use.** Read-heavy workloads where query volume dwarfs write volume — content platforms, feeds, profile views, large public APIs. The article notes social platforms route feed generation and search to replicas while writes stay on the primary.

**Trade-offs.** Horizontal read scaling, a write-focused primary, and replica redundancy for availability — but replication lag means read-your-write is not guaranteed (users can briefly see stale data), and failover/promotion when the primary dies is operationally tricky.

### Global (distributed) rate limiting

**What it is.** Enforcing per-client request quotas against a shared, centralized counter store (typically Redis) rather than per-server memory. The article's key insight: purely local limiters break behind a load balancer, because a client sprayed across N servers effectively gets N times the quota.

**When to use.** Any multi-server API surface: gateway-level API quotas (Stripe/Twitter-style), login endpoints (brute-force defense), payment operations, and AI platforms metering costly compute.

**Algorithms covered.** Token bucket (refill at a fixed rate, each request spends a token), leaky bucket (drain at a constant rate), sliding window (count within a moving interval), and fixed-window counters (simplest, least accurate at boundaries). Tooling named: Redis, NGINX, Envoy, API gateways, Cloudflare.

**Trade-offs.** Protects infrastructure, tames abuse, and enables fair sharing and cost control; the price is an extra shared dependency, cross-node synchronization concerns, and UX damage if limits are miscalibrated.

### Pattern-to-problem mapping (closing taxonomy)

The article ends with a one-line map worth keeping: write-behind cache → write latency; thundering-herd defenses → spike stability; distributed transactions → strong consistency; materialized views → read latency; bulk processing → throughput; read replicas → read scale-out; global rate limiting → system protection. Useful as a triage index when diagnosing which class of bottleneck a system has.

## Not absorbed

- Opening framing about millions of users and name-drops of Netflix/Amazon/Uber/Google/Meta — motivational scene-setting, no technical content.
- The claim that mastering these patterns makes you think like a systems architect, plus the sign-off — interview-prep encouragement.
- Engagement metadata in the capture (view/like/reply counts, timestamp) — platform chrome, not article content.

## Fidelity check

**Post count in capture:** 1 (single long-form article post; no thread breaks present).

**Article outline as authored:**
1. Introduction (why distributed patterns matter + list of the seven)
2. Write-Behind (Write-Back) Cache
3. Thundering Herd Problem
4. Distributed Transactions & Two-Phase Commit (2PC)
5. Materialized View Pattern
6. Bulk Processing Pattern
7. Read Replica Architecture
8. Global Rate Limiting
9. Closing summary (pattern → problem-category mapping)

**Pattern-to-section citations:**
- Write-behind caching → section 1 ("Write-Behind (Write-Back) Cache")
- Thundering-herd mitigation → section 2 ("Thundering Herd Problem")
- Distributed transactions via 2PC → section 3 ("Distributed Transactions & Two-Phase Commit (2PC)")
- Materialized views → section 4 ("Materialized View Pattern")
- Bulk processing → section 5 ("Bulk Processing Pattern")
- Read-replica architecture → section 6 ("Read Replica Architecture")
- Global rate limiting → section 7 ("Global Rate Limiting")
- Pattern-to-problem mapping → closing summary section
