# Digest: Design A Distributed Cache

- **Source:** https://x.com/Harry_The_Nerd/status/2048052028174463278
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Cache as a speed layer, not a store of record
A distributed cache holds only ephemeral copies of hot data in RAM, positioned in front of a
database that remains the single source of truth. The defining contrast with a distributed
key-value store is durability intent: the KV store owns the data permanently at terabyte scale,
while the cache holds an expiring working set sized to memory. Because every cached entry is a
duplicate of something durable elsewhere, losing the entire cache costs latency, never data.
Use this framing to decide what belongs in the cache (recomputable/refetchable hot reads) and to
justify why cache-node failure handling can be simple.

### Minimal functional contract for a cache
The core API is small: a put that accepts a key, value, and TTL; a get that returns either the
value or a miss; eviction when memory fills; invalidation when the origin changes; and a defined
miss path (read the DB, populate the cache, return the value). Keeping the contract this narrow is
what lets each node stay independent and horizontally scalable.

### Cache-aside (lazy loading)
The application owns the population logic: on a miss it reads the DB and writes the result into
the cache itself. Memory is spent only on keys someone actually asked for. Trade-offs: the first
read of any key pays full DB latency, and a cache outage sends the entire read load straight to
the DB. Preferred default for read-heavy workloads.

### Write-through
Every write lands in cache and DB together, and success is reported only after both confirm.
The cache can never serve stale data because it is updated in the same operation as the origin.
Costs: each write carries the latency of both systems, and the cache accumulates entries that may
never be read. Fits write-heavy workloads where consistency matters more than write speed.

### Write-behind (write-back)
Writes hit only the cache and return immediately; a background job flushes them to the DB later.
This gives the fastest possible write path, but any node crash between acknowledgment and flush
permanently loses those writes. Only acceptable where losing some recent writes is tolerable
(e.g., counters, analytics-ish data). The author's selection heuristic: read-heavy → cache-aside;
write-heavy plus consistency → write-through; write-heavy plus raw speed → write-behind.

### Consistent hashing for key placement
Nodes are placed on a virtual hash ring; a key is routed clockwise to the first node it meets.
Routing is an O(1) decision with no directory lookup per request, and when a node joins or leaves,
only roughly 1/N of the keyspace remaps instead of nearly all of it. This is the mechanism behind
both instant key location and low-disruption horizontal scaling.

### Eviction policy choice: LRU vs LFU (and the hybrid)
When a node's RAM is full, LRU discards the entry idle the longest — right for recency-dominated
access (feeds, sessions, recent searches). LFU discards the entry with the lowest lifetime access
count — right for popularity-dominated access (top videos/songs), since a globally popular item
survives quiet periods. Production systems (Redis is cited) pair LFU eviction with TTL expiry so
that frequency decides what stays under memory pressure while TTL clears out historically popular
but now-stale entries.

### Invalidation strategy 1: TTL expiry
Attach a lifetime to every entry and let staleness resolve itself when the timer runs out. Zero
coordination cost, but there is a bounded window during which reads can see outdated data. Suited
to non-critical data where a short stale window is acceptable.

### Invalidation strategy 2: event-driven (CDC-style via a message bus)
On a DB update, publish a change event (Kafka in the article); a cache-side consumer deletes the
affected key, so the next read repopulates fresh from the DB. Staleness window shrinks to
near-zero at the cost of running an event pipeline. The choice for correctness-critical data.

### Invalidation strategy 3: version tagging
Each cached entry stores a version number mirroring a version column in the DB; a read compares
the two and treats a mismatch as a miss, refetching. Gives precise per-read freshness checks but
requires schema support for version tracking and a comparison on the read path.

### Cold start as an accepted trade-off
Since cache state is RAM-only, a restarted node comes back empty. Rather than engineering
persistence, the design accepts a warm-up period: each miss repopulates the entry from the DB
until the hot set is rebuilt. This is the deliberate price of keeping the cache a pure speed
layer.

### Data-plane / control-plane split
Three storage roles, none of them a durable DB owned by the cache: (1) per-node RAM holding key,
value, TTL, and version; (2) a coordination service (Zookeeper) holding the ring configuration,
node-health state fed by a gossip protocol, and cluster policy defaults (eviction policy, TTL,
per-node size limits); (3) a message bus (Kafka) carrying invalidation events from the DB to cache
consumers. Cluster metadata and data payloads travel through entirely separate systems.

### End-to-end request and failure flow
Read path: client → app server → hash-ring routing to the owning cache node → microsecond hit, or
on a miss a DB fetch, cache populate with TTL, then return. Background planes: invalidation events
on the bus, gossip for liveness, Zookeeper for ring/policy state. On node failure, gossip detects
it within seconds, the coordination layer updates the ring, traffic reroutes, and in the interim
reads fall through to the DB — slower but correct. The system is designed to degrade gracefully
instead of failing outright.

### Non-functional targets
Latency: RAM residency plus O(1) routing targets sub-millisecond responses on hits, keeping DB
load low. Scalability: capacity grows by adding ring nodes with minimal key remapping and no
cross-node coordination on the read/write path. Availability: DB fallback plus automatic failure
detection and rerouting means a lost node reduces speed, not correctness.

## Not absorbed

- Series branding ("High-Level Design Question-Based Series #8") — interview-prep framing, not
  engineering content.
- Audience address and sign-off ("legends", "That's all, folks...Cheers!") — stylistic filler.
- Engagement metadata in the capture (view/like/reply counts, timestamp) — platform noise.
- The "Rahul" / "user:123" example literals — illustrative placeholders only; the mechanics they
  illustrate are absorbed into the pattern sections above.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; `postCount: 1` in the JSON,
  no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline (author's own section order):**
  1. Intro — cache as a speed layer
  2. Cache vs Distributed Key-Value Store
  3. Functional requirements
  4. Cache writing strategies (Cache Aside / Write Through / Write Behind + rule of thumb)
  5. Distributing across nodes — consistent hashing
  6. Eviction policies (LRU / LFU / Redis hybrid)
  7. Cache invalidation — handling stale data (TTL / event-driven / version-based)
  8. Cold start — what happens when a node restarts
  9. The data layer (RAM / Zookeeper / Kafka)
  10. The full architecture
  11. Non-functional requirements (Latency / Scalability / Availability)
  12. Sign-off
- **Pattern-to-section citations:**
  - Cache as a speed layer → sections 1 (intro) and 2 (Cache vs Distributed Key-Value Store)
  - Minimal functional contract → section 3 (Functional requirements)
  - Cache-aside → section 4 (Cache writing strategies: Cache Aside)
  - Write-through → section 4 (Cache writing strategies: Write Through)
  - Write-behind + selection heuristic → section 4 (Cache writing strategies: Write Behind +
    rule of thumb)
  - Consistent hashing → section 5 (Distributing across nodes)
  - LRU vs LFU + hybrid → section 6 (Eviction policies)
  - TTL invalidation → section 7 (Cache invalidation: TTL)
  - Event-driven invalidation → section 7 (Cache invalidation: event-driven)
  - Version tagging → section 7 (Cache invalidation: version-based)
  - Cold start trade-off → section 8 (Cold start)
  - Data-plane / control-plane split → section 9 (The data layer)
  - End-to-end request and failure flow → sections 10 (The full architecture) and 11
    (Non-functional requirements: Availability)
  - Non-functional targets → section 11 (Non-functional requirements)
