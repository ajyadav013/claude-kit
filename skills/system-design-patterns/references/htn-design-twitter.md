# Digest: Design Twitter (HLD)

- **Source:** https://x.com/Harry_The_Nerd/status/2068309801638195531
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Read/write ratio as the primary design driver
The article anchors the whole design on a capacity model: 200M DAU, 150M original tweets/day (mix: 60% text, 30% image, 10% video), roughly 200 TB/day of new storage (video-dominated), and — most importantly — a read/write ratio near 3:1. Because the audience actively replies, likes, and retweets rather than passively scrolling, the write path must scale as seriously as the read path. Use this framing whenever a system's users are producers as much as consumers; it changes where you invest (write buffering, async fan-out) versus a read-heavy CDN-style design.

### Media bypasses the API gateway via presigned URLs
Binary payloads never transit the gateway. Clients authenticate, request a short-lived presigned S3 URL from the owning service, and upload straight to object storage; a worker then produces derived variants, and a CDN fronts the bucket. Applies to profile photos/banners and tweet media alike. Trade-off: more moving parts (event triggers, async processing state) in exchange for keeping the gateway thin and cheap.

### Gateway-level rate limiting as write-spike shedding
Beyond auth and routing, the gateway is the first defense against synchronized global-event write bursts (e.g., a World Cup goal): excess traffic is shed before it can reach downstream services. Trade-off: some legitimate writes get throttled during peaks, accepted in exchange for keeping the core write path alive.

### Denormalized counters maintained asynchronously
Follower/following/tweet counts on the user row, and like/retweet/reply/view counts on the tweet row, are cached columns updated by Kafka consumers — never computed by counting rows at read time, which would be prohibitively slow at this scale. The interaction tables (Likes, Retweets, Replies) remain the source of truth; the counters are the fast read path. Trade-off: counts are eventually consistent, which the requirements explicitly permit (strong consistency is reserved for follow edges and tweet existence).

### Relational follow edges plus a graph DB for multi-hop queries
Follows live in a two-column PostgreSQL table (composite PK, indexed both directions) — follow is an insert, unfollow a delete, first-degree lookups are simple indexed scans. Second-degree questions (suggested follows, mutuals) go to a dedicated graph store (Neo4j / Neptune) because multi-hop traversal is native there and expensive as relational self-joins. The table is sharded by follower_id once it reaches billions of rows. Trade-off: two stores to keep in sync, each serving the query shape it is good at.

### Redis write buffer in front of the durable store
During write spikes, tweets are accepted into Redis immediately, an event is published to Kafka, and a consumer drains into PostgreSQL at a sustainable rate off the hot path. Like/retweet counter increments follow the same shape (increment in Redis, flush later). This is the anti-thundering-herd pattern for writes: the database never sees the raw spike. Trade-off: a window where data exists only in Redis + Kafka before landing in the relational store.

### Event-driven media transcoding fan-out
S3 upload completion emits an event; a horizontally scaled transcoding pool produces image variants (thumbnail/medium/full, WebP) and video renditions (360p–1080p, HLS-chunked, preview thumbnail), stores them under a per-tweet key layout, then publishes a completion event consumed independently by three workers: metadata persistence + cache population, search indexing, and feed fan-out. Transcoding is the acknowledged bottleneck for media posts; the fix is simply more workers, since Kafka decouples producers from consumer speed.

### Hybrid feed fan-out (write for most, read for celebrities)
The algorithmic feed is precomputed at write time: a fan-out worker inserts each new tweet into every follower's per-user Redis sorted set (member = tweet id, score = relevance blending recency, engagement, and relationship closeness), so a single ZREVRANGE serves the top of the feed. Accounts above a follower threshold (~1M) skip fan-out entirely; their recent tweets sit in a dedicated cache and are merged into follower feeds at read time. Trade-offs: fan-out cost for popular-but-not-celebrity authors (the stated bottleneck), and read-time merge latency proportional to celebrity followees, mitigated by short-TTL caching of the merged result.

### Read-time chronological feed as both a mode and a failover
The chronological mode needs no ranking, so it is computed on demand: fetch followees from cache, run one indexed query (composite index on user + timestamp) selecting the latest N across followed accounts, cache the page per user with a short TTL. Because it does not depend on the fan-out pipeline at all, it doubles as a degradation path when precomputation lags — a nice example of building the fallback as a first-class feature.

### Two-phase feed hydration with batched cache reads
Feed stores hold only tweet IDs; full content is fetched in a single Redis MGET round trip for the whole page (e.g., 20 records at once), falling back to PostgreSQL on misses with write-back. Separating "which IDs" from "what content" keeps feed structures small and lets tweet metadata be cached once and shared across every feed that references it.

### Three-tier caching to defuse hot keys
A viral tweet read by tens of millions concentrates load on one cache key, saturating whichever Redis node owns it. The remedy is a cache hierarchy: L1 = per-app-server in-process LRU (e.g., Caffeine) serving viral items with zero network hops; L2 = Redis for warm-but-not-viral content; L3 = PostgreSQL as truth, touched only on double misses. Thousands of app servers each holding a local copy dissolves the hot-key concentration. Trade-off: L1 introduces brief cross-server staleness, acceptable for tweet content.

### Sliding-window counters via timestamp-scored sorted sets
Per hashtag, a Redis sorted set stores tweet IDs scored by Unix timestamp. A ZCOUNT over (now − 3600, now) yields the last-hour usage in O(log N); ZREMRANGEBYSCORE periodically evicts entries older than the window. The window slides automatically with wall-clock time — no reset job, no fixed buckets. This is a general technique for "events in the last T seconds" counting at high write rates.

### Trending = spike over baseline, precomputed in batch
Trending is defined as acceleration, not volume: a tag qualifies when its last-hour count sits far above its 24-hour average, so perennial giants don't trend forever. A batch worker every 1–5 minutes ranks tags by that spike ratio and writes the top 50 to a single short-TTL key; clients do one GET, zero read-time computation. Hashtag extraction itself is a Kafka consumer off the tweet-created topic, so posting never waits on it. Personalized trending reuses the same worker with location/interest filters and a longer per-user cache TTL. Ingest math: 150M tweets/day ≈ 1,700/sec, handled by horizontally scaling the extraction pool.

### Search with engagement-weighted ranking and lazy count sync
Elasticsearch indexes tweets, users, and hashtags-as-terms; relevance blends text match with engagement signals (likes, retweets, follower counts; verified boosts user search). Two sync disciplines: new/changed documents index promptly via Kafka consumers, but engagement-count updates are batched periodically because search results don't need real-time counts. Hot queries are answered from a short-TTL Redis cache before touching the cluster.

### Two-layer idempotency for interactions
Likes/retweets are deduplicated first by a Redis set membership check on the hot path (reject if present, then add + increment), and second by a UNIQUE constraint in PostgreSQL as the durable safety net. Even under retries or race conditions, a duplicate cannot persist. The pattern: cheap in-memory guard for the common case, database constraint as the invariant of record.

### Retweets as references with retweeter-side fan-out
A retweet stores no content — only a pointer row to the original. Crucially, it fans out to the *retweeter's* followers (the original author just gets a notification), which is what makes retweet-driven virality a distribution mechanism rather than a copy mechanism. Replies are ordinary tweets with a parent pointer, reusing the entire creation pipeline.

### Notification coalescing
Interaction events from every service converge on a notification consumer that collapses bursts into aggregate pushes ("X and N others liked…") instead of thousands of individual APNs/FCM sends. Device tokens in a per-user Redis hash; in-app notifications persisted relationally and delivered over WebSocket while the app is open.

### Durability and recovery posture
Kafka sits under every async path, so interactions survive downstream outages — consumers lag and catch up rather than lose events. Complementary resilience moves: read replicas for all relational reads, CDN edge-serving for all media, stateless restartable batch workers (trending), and the chronological feed as an independent read path when the fan-out pipeline degrades.

## Not absorbed

- Series framing ("Questions-Based Series #19") and the closing sign-off — interview-prep packaging, not engineering content.
- Cross-references to the author's earlier designs (Tinder's WebSocket layer, "same as Instagram", "same pattern as all previous designs") — pointers to other episodes rather than material taught here.
- The out-of-scope list (DMs, Spaces, Blue/verified, ads, analytics) — scoping decisions for the exercise, no technique attached.
- The named-vendor Technology Choices table (Kong, CloudFront/Akamai, etc.) — a recap of choices already justified in earlier sections; the rationale is captured under the patterns above.
- View/like/reply metrics at the end of the capture — page chrome, not article content.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; no author-post breaks present).
- **Article outline as authored:**
  1. Requirements (functional / out of scope / non-functional)
  2. Capacity Estimation
  3. API Gateway
  4. User Service
  5. Tweet Service and Upload Pipeline
  6. Feed Service
  7. Trending Service
  8. Search Service
  9. Interaction Service
  10. Notification Service
  11. Full Data Flow Summary
  12. Resilience and Fault Tolerance
  13. Technology Choices Summary
- **Pattern → section mapping:**
  - Read/write ratio as design driver — §2 Capacity Estimation (non-functional targets from §1)
  - Presigned-URL media bypass — §3 API Gateway and §4 User Service (reused in §5)
  - Gateway write-spike shedding — §3 API Gateway
  - Async denormalized counters — §4 User Service and §5 Tweet Service data models
  - SQL follow edges + graph DB for multi-hop — §4 User Service
  - Redis write buffer before the durable store — §5 Tweet Service (Write Spike Handling; reiterated §12)
  - Event-driven transcoding fan-out — §5 Tweet Service and Upload Pipeline
  - Hybrid feed fan-out — §6 Feed Service (Algorithmic Feed)
  - Chronological feed as mode + failover — §6 Feed Service (Chronological Feed) and §12 Resilience
  - Two-phase hydration with MGET — §6 Feed Service (Feed Hydration)
  - L1/L2/L3 hot-key caching — §6 Feed Service (Hot Key Problem; reiterated §12)
  - Sliding-window sorted-set counters — §7 Trending Service
  - Spike-over-baseline trending, batch precompute — §7 Trending Service
  - Engagement-weighted search + batched count sync — §8 Search Service
  - Two-layer idempotency — §9 Interaction Service (Like Flow) and §12 Resilience
  - Retweet-as-reference, retweeter-side fan-out — §5 (Retweets table) and §9 (Retweet Flow)
  - Notification coalescing — §10 Notification Service
  - Kafka durability / recovery posture — §12 Resilience and Fault Tolerance
- **Capture oddities:** In §8 the headings for the two Elasticsearch document examples appear with no body beneath them — the schemas were likely images in the original post and did not survive the text render. §11 is a condensed restatement of flows from §3–§10 (ASCII flow summaries); no patterns were sourced solely from it.
