# Digest: Design Tinder (High-Level Design)

- **Source:** https://x.com/Harry_The_Nerd/status/2065790968448909572
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Capacity estimation to find the dominant load path

Before designing anything, size every flow: 10M DAU x ~50 swipes each yields ~500M swipe events
per day (~6,000/s at peak), a ~1-2% right-swipe match rate gives ~5M matches/day, matched pairs
average ~10 messages/day (~50M messages/day), and 50M registered users x ~5 photos x ~1 MB is
roughly 250 TB of write-once media. The point of the exercise is prioritization: the numbers
reveal that swiping — not media serving or chat — is the system's dominant write path, so the
architecture is optimized around discovery and swipe handling. Use this whenever early estimates
can redirect design effort; the trade-off is that rough per-user assumptions can be wrong, so
treat the output as ordering guidance, not SLAs.

### Keep binary media out of the API gateway (presigned upload URLs)

The gateway does auth, rate limiting, and routing only. Photo uploads get authenticated, then the
profile service hands the client a time-limited presigned object-storage URL and the client pushes
bytes straight to blob storage (S3). Backend services never proxy image payloads. Use for any
user-generated media at scale; the trade-off is a slightly more complex client flow and the need
for a separate completion signal (here, a storage event).

### Event-driven media variant pipeline behind a CDN

A storage-upload event flows through Kafka to a worker that renders multiple resolutions (a small
thumbnail for the card stack, a medium size for the full profile) and writes them back to blob
storage. A CDN fronts the bucket; because profile photos change rarely, cache hit rates stay high.
Use when derived assets (resizes, transcodes) can be produced asynchronously; the trade-off is a
short window where variants do not yet exist after upload.

### Composite indexes shaped exactly like the query

Discovery filters on gender, orientation preference, relationship type, and an age range. One
composite index covering that exact column set lets Postgres answer the whole filter in a single
index scan instead of a table scan. The general rule: build the index from the query's WHERE
shape, equality columns first, range column last. Trade-off: each composite index taxes writes and
only serves queries matching its prefix.

### Geohashing / Redis GEO for proximity search

Radius search over raw lat/long columns needs a simultaneous range scan on two floats, which
indexes poorly. Geohashing folds 2D coordinates into one string where nearby places share a
prefix, turning "within ~50 km" into a prefix match; 5-6 characters of precision yields cells
around 5-10 km, which suits a dating radius. Rather than hand-rolling this, the design uses Redis
GEO (geohash-backed sorted sets under the hood): GEOADD to upsert a position atomically, GEORADIUS
to pull everyone in range. Memory cost is modest — on the order of 100 bytes per user, so ~1 GB
for 10M actives. Trade-offs: in-memory data is not durable by default (see the resilience pattern
below), and grid-cell approaches have edge effects near cell boundaries that the native radius
command hides from you.

### Client-side throttling of high-frequency updates

If every phone reported position every few seconds, location writes would swamp the system. The
client only sends an update after moving beyond a threshold (~500 m) or when the app opens. This
pushes rate limiting to the edge where the signal ("did anything meaningful change?") is cheapest
to compute. Use for any sensor-ish telemetry; the trade-off is bounded staleness between updates.

### Bloom filter for already-seen exclusion

A hard product rule — never re-show a swiped profile — would naively require joining every
discovery request against a user's full swipe history (potentially tens of thousands of rows). A
Bloom filter answers "seen before?" from a fixed bit array and 3-4 hash functions: membership adds
set several bit positions; a lookup that finds any zero bit means definitely-not-seen, all ones
means probably-seen. Properties that make it fit: zero false negatives (a seen profile is always
filtered), a small false-positive rate (occasionally suppressing an unseen candidate, which is
harmless in a large pool), and tiny memory (KBs where a Redis Set of 100k IDs would take MBs).
RedisBloom provides BF.ADD / BF.EXISTS natively. Trade-offs: you cannot delete members, cannot
enumerate them, and the false-positive rate grows if the filter is undersized for its item count.
The key judgment call is matching the failure mode to the product: skipping a valid candidate is
fine; repeating a rejected one is not.

### Funnel-ordered candidate pipeline: cheap in-memory cuts before disk

Discovery runs a five-step funnel: (1) GEORADIUS returns everyone in range — possibly ~100k IDs in
a dense city; (2) Bloom-filter checks drop already-seen candidates entirely in memory; (3) only the
survivors hit Postgres, where the composite index applies age/gender/relationship filters with a
LIMIT of ~50; (4) the final 20-50 IDs are hydrated from cache; (5) ~20 cards return to the client
inside the 100 ms budget. The ordering principle: each stage should shrink the set using the
cheapest available check before anything touches a disk-backed store. Safety valve for extreme
density: shrink the radius dynamically or cap the pool before the SQL stage.

### Batched cache hydration with read-through backfill

Fetching 20-50 full profiles uses one Redis MGET — a single round trip for the whole batch —
instead of N sequential gets. Misses fall back to Postgres and the fetched rows are written back
into the cache. Standard read-through caching, with the batching as the notable discipline: hot
paths should never issue per-item round trips for a known ID list.

### Kafka-first ingestion; durable persistence off the hot path

Every swipe is published to Kafka before any downstream work happens. This does two jobs at once:
durability (a slow or dead consumer never loses a swipe — events wait in the log) and decoupling
(the synchronous path only does the in-memory work that affects user experience). A consumer
writes swipes to the permanent Postgres table asynchronously, keeping the only disk write out of
the latency-critical path. Use for any high-volume event stream with fan-out consumers; the
trade-off is eventual consistency between the live state and the system of record.

### Atomic mutual-intent detection with Redis sets

Match logic on a right swipe: SISMEMBER on the other user's pending-likes set. A hit means both
liked each other — write the match, emit a match event for notifications. A miss means SADD
yourself into their pending set and wait. Correctness leans on Redis executing commands
single-threaded: two simultaneous mutual right-swipes cannot both miss, because one SADD lands
before the other's SISMEMBER runs. This satisfies the "never miss or double-fire a match"
requirement without distributed locks. The pattern generalizes to any symmetric handshake
(mutual follows, trade matching) where a single serialized store can arbitrate.

### Bound every hot in-memory collection

Pending-likes sets are unbounded by nature — a very popular user can accumulate hundreds of
thousands of entries. The design caps set size per user and evicts old entries unlikely to
convert. General lesson: any per-entity Redis structure fed by other users' actions needs an
explicit growth bound, or your memory profile is hostage to your most popular entity.

### WebSockets plus a Redis Pub/Sub bus for cross-server chat delivery

Chat needs server push, so each client holds a persistent bidirectional WebSocket. But sockets are
stateful: the two ends of a conversation usually terminate on different chat-server instances, and
server 1 cannot write to a socket held by server 3. Instead of server-to-server mesh routing, every
chat server subscribes to a Redis channel per active conversation; a sent message is published to
chat:{match_id} and whichever server holds the recipient's socket pushes it down. Redis becomes the
message bus. Noted limit: pub/sub throughput on a single scorching channel — irrelevant for
two-person conversations, relevant if you reuse the pattern for large rooms.

### Conversation-partitioned wide-column message storage

Message history access is always "one conversation, chronological, paginated" — an ideal
Cassandra shape. Partition key = match_id (a conversation's messages colocate on one node),
clustering key = time-ordered message ID (rows come back already sorted). Replication factor 3
across availability zones covers node loss. Trade-off: you give up ad-hoc cross-conversation
queries in exchange for very fast single-partition reads and high write throughput.

### Sorted-set cache for the recent window

The active conversation view needs only the newest ~50 messages, so they are mirrored into a Redis
Sorted Set keyed by conversation, scored by timestamp; one ZREVRANGE call returns the window in
order. Scroll-back beyond the window goes to Cassandra. This is the "hot window in memory, long
tail on disk" split applied to messaging.

### Presence via heartbeat plus TTL expiry

Online status is a Redis key per user with a 30-second TTL; the open app heartbeats every 15
seconds, refreshing the TTL. Close the app or lose the network and the key simply expires — the
user goes offline with no explicit logout, no server-side polling, and graceful handling of
crashes and dead radios. The two-heartbeats-per-TTL ratio tolerates one dropped beat. Trade-off:
offline detection lags by up to the TTL.

### Scaling a stateful socket fleet

Each chat server holds a finite number of concurrent sockets (roughly 10k-50k depending on
memory), so 10M DAU implies hundreds of instances. Sticky sessions (or consistent hashing on user
ID) at the load balancer send a reconnecting client back to its previous instance. When a server
dies, clients reconnect elsewhere and the new server re-subscribes to the needed pub/sub channels
and reloads the recent-message sorted set — connection state is rebuilt, not replicated.

### Tiered durability: caches must be rebuildable, and losses ranked by blast radius

Every in-memory structure has a durable source it can be reconstructed from, and the design
explicitly grades what each loss costs. Redis GEO lost? Rebuild from the async-written Postgres
location table; briefly stale positions are low-stakes. Bloom filter lost? The user may briefly
see repeats until it is rebuilt from the permanent swipe history — a UX blemish, not corruption.
Kafka retention means downstream consumers can crash and replay. The discipline: for each cache,
name the rebuild source and consciously classify the failure as integrity-critical or
annoyance-only; only the former justifies heavier machinery.

## Not absorbed

- Series branding ("Questions-Based Series #17") — interview-prep framing, not engineering content.
- Out-of-scope pointers to the author's earlier Instagram-design article and a separate
  notifications article — cross-promotion of other posts.
- "Advanced ML ranking acknowledged but not designed" — an explicit non-design, nothing to absorb.
- Closing sign-off and the trailing view/like/repost counts in the capture — engagement chrome.

## Fidelity check

- **Post count in capture:** 1 (a single long-form article post; the JSON reports postCount 1 and
  contains no ---AUTHOR-POST-BREAK--- separators).
- **Article outline as authored:**
  1. Requirements (functional / out of scope / non-functional)
  2. Capacity Estimation
  3. API Gateway
  4. User Profile Service
  5. Location Service
  6. Discovery Service
  7. Swipe Service
  8. Chat Service
  9. Full Data Flow Summary
  10. Resilience and Fault Tolerance
  11. Technology Choices Summary
- **Pattern-to-section citations:**
  - Capacity estimation to find the dominant load path — section 2 (Capacity Estimation).
  - Keep binary media out of the API gateway — sections 3 (API Gateway) and 4 (User Profile
    Service, upload flow).
  - Event-driven media variant pipeline behind a CDN — section 4.
  - Composite indexes shaped exactly like the query — section 4 (indexing strategy), reused in
    section 6 step 3.
  - Geohashing / Redis GEO for proximity search — section 5 (Location Service).
  - Client-side throttling of high-frequency updates — section 5 (location updates + bottlenecks).
  - Bloom filter for already-seen exclusion — section 6 (Discovery Service).
  - Funnel-ordered candidate pipeline — section 6 (full discovery pipeline + bottlenecks).
  - Batched cache hydration with read-through backfill — section 6, step 4.
  - Kafka-first ingestion; persistence off the hot path — section 7 (Swipe Service).
  - Atomic mutual-intent detection with Redis sets — section 7 (match detection) and section 10
    (match-detection consistency).
  - Bound every hot in-memory collection — section 7 (bottlenecks).
  - WebSockets plus Redis Pub/Sub bus — section 8 (Chat Service, multi-server problem).
  - Conversation-partitioned wide-column storage — section 8 (message storage) and section 10
    (Cassandra replication).
  - Sorted-set cache for the recent window — section 8 (message storage).
  - Presence via heartbeat plus TTL expiry — section 8 (online presence).
  - Scaling a stateful socket fleet — section 8 (bottlenecks) and section 10 (WebSocket
    reconnection).
  - Tiered durability / rebuildable caches — section 10 (Resilience and Fault Tolerance).
  - Section 9 (data-flow summary) and section 11 (technology table) restate earlier sections and
    contributed no additional patterns.
