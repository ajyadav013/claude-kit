# Digest: Design Instagram (HLD)

- **Source:** https://x.com/Harry_The_Nerd/status/2065074213665579192
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (High-Level Design series, #16)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Read-dominance as the governing capacity number
The author sizes the system around a roughly 1000:1 read/write ratio: 500M DAU, ~100M posts/day
(20% of DAU posting), ~5 MB weighted average per post (~1 MB photos, ~10 MB videos), giving
~500 TB/day raw and ~180 PB/year before replication and per-resolution copies. The design lesson
is to identify the single dominant asymmetry early — here, one post can be read a billion times —
and let it justify every downstream choice (edge caching, precomputed feeds, replicas). Trade-off:
a read-optimized topology makes the write path more elaborate (fanout workers, async counters).

### Consistency tiering per data class
Not everything needs the same guarantees. Feeds, like tallies, and notifications tolerate eventual
consistency; follow relationships and profile records demand strong consistency. Classifying data
this way up front lets each store be chosen for its actual requirement instead of forcing one
consistency model system-wide.

### Keep binary payloads out of the API gateway
The gateway's job is auth, rate limiting, routing, and TLS termination — never proxying media
bytes. A single video upload can exceed 100 MB, so funneling media through the gateway would turn
it into the system's choke point. Rule of thumb: control-plane traffic through the gateway, data
plane around it.

### Presigned-URL direct-to-blob upload
The client asks the Post Service (via the gateway) for a short-lived, pre-authorized S3 URL, then
pushes the file straight to object storage. Backend services touch only metadata and orchestration,
which keeps them stateless and trivially horizontally scalable. Completion is detected via a
storage event rather than an application callback. Trade-off: you give up inline validation of the
bytes at upload time and must handle it in the async pipeline instead.

### Event-triggered transcoding worker pool
The blob-store upload event lands on Kafka and drives a fleet of transcoding workers. Images get
several resolution variants (150x150 thumbnail, 640x640 feed size, full size), modern-format
compression (WebP where supported, JPEG fallback), and a blurred instant-loading placeholder.
Videos get 360p/480p/720p/1080p renditions, HLS segmenting for adaptive bitrate, and a preview
frame. Transcoding is the CPU bottleneck of the write path, but each job is independent, so a
queue-fed worker pool scales linearly.

### Deterministic storage layout instead of a lookup service
Variants are written under a predictable path scheme (media/{post_id}/{variant}/), so any service
can compute a media URL without querying anything. Convention replaces a lookup dependency —
cheap, but it locks the path contract in place.

### Kafka fanout for decoupled downstream consumers
A single post-transcoded event feeds independent consumers: a metadata writer (Posts DB + Redis
cache), a search indexer (Elasticsearch), and a feed fanout worker. Producers know nothing about
consumers, and a downed consumer simply falls behind its durable offset and replays on recovery —
no loss, no cross-service blast radius. This same pattern recurs for likes/comments/follows
feeding notifications and analytics.

### CDN edge caching exploiting power-law popularity
A CDN fronts object storage, absorbing about 90% of media reads for popular content. Because a
tiny slice of posts drives most views, hot items reach edge caches almost immediately and stay
warm for days. Each resolution variant is a distinct object with its own cache entry, so clients
always fetch the cheapest rendition their display context needs (grid thumbnail vs feed medium vs
full view).

### Hybrid feed fanout: push for normal users, pull for celebrities
Pure fan-out-on-write breaks at celebrity scale — writing one post into 100M follower feeds would
take on the order of 100 seconds even at 1 microsecond per write. The hybrid: accounts below a
follower threshold (roughly 1M) are pushed into each follower's precomputed feed at post time;
accounts above it write only to a celebrity-posts cache, which is pulled and merged into the
follower's feed at read time. The read path fetches the precomputed set, pulls latest celebrity
posts, merges, re-ranks, and returns the top 20 IDs.

### Redis sorted set as the precomputed feed store
Each user's feed is a sorted set keyed by user ID, members are post IDs, and the score is a
composite of recency and engagement/affinity signals. A single reverse-range call returns the top
N in sub-millisecond time. Feeds are capped around 1000 entries with automatic eviction of stale
low scorers — generous, since users rarely scroll past a few dozen posts. Cost: substantial Redis
memory at 500M users, addressed by evicting inactive users' feeds (rebuilt from the DB on next
login) and by skipping fanout for long-idle users entirely.

### ID-then-hydrate reads with batched cache fetches
Feed reads return IDs only; the service then hydrates them with one batched multi-get against the
post-metadata cache. The latency math is explicit: 20 sequential 1 ms cache calls would eat 20 ms
of a 100 ms feed budget, while one round trip does not. Misses fall through to the Posts DB and
are written back to the cache. The response carries everything needed to render — metadata, CDN
media URLs, author info, counters.

### Asynchronously maintained denormalized counters
Like, comment, follower, and following counts live as columns on the post/user rows, incremented
by Kafka consumers rather than computed by aggregation queries at read time. The interaction
tables remain the source of truth for "did X like Y"; the denormalized column is only the
displayed number. Trade-off: displayed counts lag slightly, which the consistency tiering already
permits.

### Relational join table for edges, graph DB for traversals
First-degree follow relationships are a plain many-to-many table with a composite primary key —
insert to follow, delete to unfollow, one indexed predicate to list followees. Multi-hop questions
(mutuals, friends-of-friends, suggestions) move to a graph database (Neo4j/Neptune) because deep
traversals that are native in a graph engine are prohibitively expensive as SQL self-joins. Use
each store for the query shape it is good at.

### Engagement-weighted search over one index of mixed entities
Elasticsearch indexes posts, users, and hashtags together, supporting fuzzy/partial matching in a
single query. Ranking blends text relevance with engagement: a weak text match with 50k likes can
beat an exact match with 3, and user search leans on follower count and verification. Hashtags are
first-class indexed entities, so tapping one is just a field-scoped search. Sync discipline:
index updates flow from Kafka topics; like-count updates are batched periodically because search
results do not need real-time counters; hot queries get a short-TTL Redis cache; and the index
carries only fields needed for matching and ranking, not whole documents.

### Notification coalescing with a time window
One push per like would be absurd for a viral post, so similar events on the same post inside a
~30-second window collapse into a single message ("X and 499 others liked..."). Delivery goes
through a device-token store to APNs/FCM (platforms own the last mile), while in-app bell history
persists to PostgreSQL and reaches open clients via polling or WebSocket. Even with coalescing,
event-processing throughput must handle spikes like a million likes an hour, so workers scale
horizontally and coalescing windows widen under load.

### Degraded-mode resilience via cache-first layering
Failure isolation falls out of the read architecture: the CDN keeps serving hot media even if
origin storage is unreachable; Redis-resident feeds keep loading even if the Posts DB is down
(new posts pause, existing content survives); Kafka's durable offsets let any worker die and
catch up. Circuit breakers stop a slow dependency from hanging its callers — a sluggish Redis
triggers DB fallback rather than an indefinite wait. Relational reads ride replicas (writes to
primary only), and high-volume append paths use Cassandra at replication factor 3 across
availability zones.

## Not absorbed

- Series branding and numbering ("Questions-Based Series #16") — interview-prep framing, not
  engineering content.
- Repeated pointers to the author's Spotify article (#15) for the gateway constraint and
  transcoding pipeline — cross-promotion of another post; the ideas themselves are captured above.
- The worked micro-example of a user following 500 accounts producing 1000 candidate posts/day —
  motivational arithmetic for the feed section, already subsumed by the fanout patterns.
- Closing sign-off and engagement metrics (views/likes/reposts) — social chrome.
- The "Elasticsearch Documents" subsection lists headings for a post document and a user document
  but no field content survived the capture (likely images) — nothing to absorb.

## Fidelity check

- **Post count in capture:** 1 (the entire article is a single long-form post; no
  ---AUTHOR-POST-BREAK--- separators present).
- **Article outline as authored:**
  1. Requirements (functional, out-of-scope, non-functional)
  2. Capacity Estimation
  3. API Gateway
  4. Upload Pipeline (5 steps + bottlenecks)
  5. Media Serving and CDN
  6. Feed Generation (fan-out on write, fan-out on read, hybrid, hydration, bottlenecks)
  7. Post Service and Data Model (Posts, Users, Follows, Likes, Comments)
  8. Search Service
  9. Notification Service
  10. Full Data Flow Summary
  11. Resilience and Fault Tolerance
  12. Technology Choices Summary
- **Pattern-to-section mapping:**
  - Read-dominance as the governing capacity number — Section 2 (Capacity Estimation)
  - Consistency tiering per data class — Section 1 (Requirements, non-functional)
  - Keep binary payloads out of the API gateway — Section 3 (API Gateway)
  - Presigned-URL direct-to-blob upload — Section 4 (Upload Pipeline, steps 1-2)
  - Event-triggered transcoding worker pool — Section 4 (step 3 + bottlenecks)
  - Deterministic storage layout instead of a lookup service — Section 4 (step 3)
  - Kafka fanout for decoupled downstream consumers — Section 4 (steps 4-5), reinforced in
    Sections 9 and 11
  - CDN edge caching exploiting power-law popularity — Section 5 (Media Serving and CDN)
  - Hybrid feed fanout — Section 6 (Feed Generation)
  - Redis sorted set as the precomputed feed store — Section 6 (Strategy 1 + bottlenecks)
  - ID-then-hydrate reads with batched cache fetches — Section 6 (Feed Hydration)
  - Asynchronously maintained denormalized counters — Section 7 (Post Service and Data Model)
  - Relational join table for edges, graph DB for traversals — Section 7 (Follows table)
  - Engagement-weighted search over one index of mixed entities — Section 8 (Search Service)
  - Notification coalescing with a time window — Section 9 (Notification Service)
  - Degraded-mode resilience via cache-first layering — Section 11 (Resilience and Fault
    Tolerance), with store assignments from Section 12
