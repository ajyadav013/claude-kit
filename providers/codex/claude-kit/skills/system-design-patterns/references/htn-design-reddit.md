# Digest: Design Reddit (HLD)

- **Title:** Design Reddit — High-Level Design Questions-Based Series #18
- **Source:** https://x.com/Harry_The_Nerd/status/2067615247259811850
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Write-load-first capacity framing
Before drawing boxes, the article sizes the workload and identifies which number dominates the design. With 50M DAU, ~10M posts/day, ~100M comments/day, and ~250M votes/day (~3,000/s sustained, far higher during viral spikes), the conclusion is that votes — not posts — are the write path that shapes the architecture, since each vote can force a ranking recomputation. Media at roughly 20 TB/day (using a ~2 MB weighted-average post size) is called out as large but routine once object storage plus CDN are assumed. Use this framing whenever the obvious "content" entity is not actually the scaling problem; the trade-off is that a design optimized for the dominant write can under-invest elsewhere, so the secondary paths still get their own bottleneck analysis per section.

### Keep the gateway out of the binary path (presigned direct upload)
The API gateway does auth, rate limiting, and routing only; image/video bytes never transit it. Clients authenticate, request a presigned object-storage URL from the post service, and upload straight to S3. Use when payloads are large and the gateway would otherwise become a bandwidth bottleneck. Trade-off: the upload becomes asynchronous relative to post creation, so you need an event pipeline to finish the job.

### Event-driven transcoding fan-out
An S3 upload event feeds Kafka, which drives a horizontally scaled transcoding worker pool: images get thumbnail/medium/full variants with compression and WebP; videos get multiple resolutions (360p–1080p), HLS chunking for adaptive playback, and a poster frame. Outputs land in S3 under a predictable per-post/per-variant path. Completion emits a `post.transcoded` event consumed independently by a metadata writer (Posts DB + Redis cache) and a search indexer (Elasticsearch). Text-only posts skip the whole pipeline and write straight to the DB, emitting `post.created`. Use when derived-media generation is CPU-bound and must not block the request path; the trade-off is eventual visibility of media posts and more moving parts (queue, workers, multiple consumers).

### Denormalized counters maintained asynchronously
The posts table carries upvote/downvote/score/hot-score columns kept current by Kafka consumers rather than computed by aggregation at read time. Use when read volume dwarfs write volume and exact-to-the-instant counts are unnecessary. Trade-off: the columns are eventually consistent and can drift, which is why a reconciliation job exists (below).

### Two-layer vote idempotency
Duplicate-vote prevention lives in two places: a Redis set lookup on the hot path (same-direction repeat is dropped; a direction flip is turned into a delta), and a database UNIQUE constraint on (user, post) as the backstop. Use when a fast in-memory check is needed for latency but retries/network failures could still slip duplicates past the cache. Trade-off: two enforcement points means the semantics (especially vote switching) must be encoded consistently in both.

### Redis-first counters with Kafka as the durability spine
A vote increments a Redis counter immediately — clients read counts from Redis, never the DB — then publishes an event to Kafka. Downstream, three independent consumers persist the vote to PostgreSQL, recompute the post's hotness, and recompute a controversial score. The queue absorbs viral bursts so slow consumers never lose votes. Use for high-rate, spike-prone write paths where the user-visible number can be near-real-time rather than transactional. Trade-offs: Redis is not durable on its own (hence reconciliation) and consistency between counter, queue, and DB is eventual.

### Debounced score recomputation
Recomputing a ranking score per vote melts down on a post taking thousands of votes per second. The recomputation worker instead groups events for the same post inside a short window (~5 seconds) and computes once per window, cutting recomputation work by orders of magnitude while keeping rankings fresh enough. Use whenever a per-event derived computation is idempotent over a batch. Trade-off: scores lag by up to the window length.

### Periodic cache-vs-source reconciliation
Redis holds the fast counters; PostgreSQL is the authoritative record. A background job periodically compares and corrects Redis against the DB to repair drift from cache restarts or dropped events. Use alongside any write-through-cache-plus-async-persist design. Trade-off: drift exists between reconciliation runs; the job itself adds DB scan load.

### Ranked feeds as sorted sets, one per entity per sort mode
Every subreddit keeps four Redis sorted sets — hot (score plus time decay), new (timestamp), top (net votes), controversial — updated in real time by the vote/post consumers. Feed reads are pure sorted-set range queries and never hit the relational store on the happy path. Use when a small fixed set of orderings must be readable in sub-millisecond time. Trade-off: memory cost scales with entities × sort modes, and every ranking change is a write amplification against these sets.

### Hybrid fan-out keyed on community size
Small communities (below a threshold around 100k members) fan out on write: a worker pushes new posts into each member's personal home-feed sorted set. Large communities fan out on read: their sorted sets are queried at request time and merged with the precomputed personal feed, so one viral post never triggers millions of feed writes. This mirrors the follower-count hybrid used for social graphs, but the pivot variable is community size. Mitigations for the read-side merge cost: cap how many large communities are merged per request, cache the merged result per user with a 30–60 s TTL, and evict-then-rebuild home feeds for inactive users. Trade-off: two code paths and a tuning knob (the threshold) that must track real membership distributions.

### Batch hydration with read-through fallback
Feeds return post IDs; metadata is fetched in one Redis MGET round trip for the page (top 25), falling back to the Posts DB on a miss and writing the result back to the cache. Media URLs point at the CDN. Use to keep the ID-ranking layer decoupled from the object layer. Trade-off: a cold cache turns one request into N DB lookups until repopulated.

### Adjacency-list comment trees with lazy loading
Each comment stores a nullable parent reference — null means top-level — which encodes arbitrary-depth threading in one relational column, no graph database required. A composite index on (post, parent) serves the two hot queries. The client never pulls a whole tree: initial load is ~20 top-level comments by score, ~3 replies each, with deeper levels fetched on demand behind a "load more" interaction; the API enforces pagination and depth limits so recursive fetches stay bounded. Comment votes reuse the same event pipeline as post votes, with thread ordering recomputed per batch and hot threads cached briefly in Redis. Use for threaded discussions of unbounded depth; trade-off is that whole-subtree operations require iterative or recursive querying, which this design deliberately forbids at the API layer.

### Search sync with relaxed score freshness
Elasticsearch indexes posts, subreddits, and users, using post score and community size as ranking signals on top of keyword relevance. New content is indexed by a Kafka consumer of the post events, but score updates are batched and pushed periodically because search-result ordering does not need per-vote precision. Popular query results are cached in Redis with a short TTL so repeat traffic rarely reaches the cluster. Use when a secondary index tolerates looser freshness than the primary ranking system. Trade-off: search rankings lag live vote activity.

### Degradation by cache independence
Because feeds are served wholly from Redis, a slow or down PostgreSQL degrades to "no new posts appear" rather than "the site is blank" — existing feed content keeps serving. Combined with Kafka buffering (a post taking 100k votes/hour just queues), the system's failure mode is staleness, not loss. Use as an explicit resilience posture: enumerate what each dependency's outage turns into. Trade-off: users can be shown stale data with no signal that writes are backed up.

## Not absorbed

- Series branding ("High-Level Design Questions-Based Series #18") and the sign-off line with cheers — interview-prep packaging, not design content.
- Out-of-scope list items that defer to earlier installments (chat "same as Tinder", search bottlenecks "same as Instagram and Spotify") — cross-promotion of other posts; the referenced designs are not explained here.
- Engagement footer (timestamp, view/like/repost counts) — platform metadata.
- The technology-choices table (section 11) is absorbed only where it names a pattern; the bare vendor list (Kong vs AWS Gateway, CloudFront vs Akamai) is name-dropping without trade-off analysis.
- The resilience bullet about Cassandra replication — Cassandra appears nowhere in the main design except a one-line analytics-store mention, so the claim has no supporting architecture in this article.

## Fidelity check

- **Post count in capture:** 1 (single long-form post; no thread breaks).
- **Article outline (author's own section order):**
  1. Requirements (functional / out of scope / non-functional)
  2. Capacity Estimation
  3. API Gateway
  4. Post Service and Upload Pipeline
  5. Voting Service
  6. Feed Service
  7. Comment Service
  8. Search Service
  9. Full Data Flow Summary
  10. Resilience and Fault Tolerance
  11. Technology Choices Summary
- **Pattern → source section:**
  - Write-load-first capacity framing → §2 Capacity Estimation
  - Keep the gateway out of the binary path → §3 API Gateway
  - Event-driven transcoding fan-out → §4 Post Service and Upload Pipeline
  - Denormalized counters maintained asynchronously → §4 (data model)
  - Two-layer vote idempotency → §5 Voting Service (steps 2 and the Votes table)
  - Redis-first counters with Kafka durability spine → §5 (steps 3–5)
  - Debounced score recomputation → §5 (bottlenecks) and §10
  - Periodic cache-vs-source reconciliation → §5 (step 6)
  - Ranked feeds as sorted sets per sort mode → §6 Feed Service
  - Hybrid fan-out keyed on community size → §6 (fan-out strategy)
  - Batch hydration with read-through fallback → §6 (home feed read flow) and §9
  - Adjacency-list comment trees with lazy loading → §7 Comment Service
  - Search sync with relaxed score freshness → §8 Search Service
  - Degradation by cache independence → §10 Resilience and Fault Tolerance

Capture caveats: two Elasticsearch document examples in §8 and the pair of comment queries in §7 appear as headings with no body — likely images or code blocks the logged-out render did not serialize. This does not affect the patterns above but means exact document/field shapes were unavailable.
