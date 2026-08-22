# Design Spotify — HLD digest

- **Source:** https://x.com/Harry_The_Nerd/status/2063952850531897396
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level system design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Estimation-driven architecture (CDN as a forcing function)
Back-of-envelope math done before drawing boxes: 200M DAU, 1B streams/day, ~5 MB per track puts
raw daily audio delivery near 1 PB. An assumed ~80% edge cache hit rate shrinks origin traffic to
roughly 200 TB/day. The point of the exercise is that the numbers dictate three design commitments
up front: an edge CDN is mandatory (origin-only serving would be economically absurd), caching has
to exist at every tier rather than only at the edge, and with reads dwarfing writes this heavily,
the whole system should privilege read latency while letting write paths run slower. Use this
technique whenever capacity math can eliminate whole architecture options before design begins.

### Gateway on the fast path only
A single API gateway fronts all client types and owns token validation, rate limiting, routing to
microservices, and normalizing protocol differences across devices. The equally important negative
rule: bulky or CPU-heavy work must never transit it. Pushing a multi-hundred-MB audio upload
through the request router would turn it into a chokepoint. Trade-off: you gain centralized
auth/limiting for cheap, small requests, but you must design explicit bypass routes for large
binary payloads.

### Direct-to-processor upload with a horizontally scaled transcoding pool
Labels upload raw audio straight to the transcoding tier, skipping the gateway. Transcoding is the
write path's dominant bottleneck — encoding one track into several bitrates, segmenting each, and
applying DRM is CPU-bound and can run minutes per long track. Because jobs are mutually
independent, the fix is a worker pool pulling from a queue, which scales linearly with worker
count. Use this shape for any CPU-heavy, embarrassingly parallel ingest workload.

### Multi-bitrate encoding for adaptive quality
Each track is encoded into several bitrate variants — 96, 128, 256, and 320 kbps — so the client
can drop to a cheaper variant when the network degrades without stopping playback. The cost is
storage multiplication (every variant stored in full) traded for seamless quality adaptation.

### Chunked HTTP streaming (HLS)
Every variant is cut into short segments (~2–10 s), each an independent, stateless HTTP object
with a deterministic URL. This one decision underpins the whole delivery story: segments are
natively CDN-cacheable, seeking means requesting the segment at that offset rather than
downloading everything prior, and bitrate switching is just the client requesting a different
variant's next segment. The client fetches a small manifest listing variants and segment URLs
(itself cacheable), then pulls segments in order. Quality adaptation is entirely client-side; the
server holds essentially no per-session state. Use HLS-style chunking whenever media delivery
must ride commodity HTTP/CDN infrastructure.

### DRM via encrypted chunks plus short-lived signed URLs
Segments are encrypted and bound to licenses only authenticated subscribers can obtain. At the
delivery layer, the streaming service issues a signed manifest URL with a short TTL tied to the
requesting user. This keeps entitlement enforcement at issue-time while the payload path stays
cacheable and stateless.

### Immutable blob storage for media artifacts
Processed segments across all variants land in object storage (S3-class). The fit argument: audio
chunks are large, written once, and never mutated in place, which matches blob-store semantics
(durability, effectively unbounded capacity, first-class CDN origin integration). Reserve
databases for mutable, queryable data; put write-once binary artifacts in object storage.

### Event-driven fanout over a durable log
When transcoding finishes, the service emits one event (e.g. a `song.transcoded` topic entry with
song ID and metadata) and is done — it never calls downstream services directly. Two independent
consumers subscribe: a metadata worker that writes to the metadata DB and refreshes its cache, and
a search-indexing worker that makes the track searchable within seconds. Consumers don't block
each other; a crashed consumer just lags its offset and replays on recovery with nothing lost.
This is the canonical way to keep several derived datastores eventually consistent without
synchronous coupling, at the cost of accepting a consistency lag window.

### Search index as a derived, read-optimized projection
Elasticsearch serves prefix/fuzzy matching, cross-entity queries (songs, artists, albums,
playlists in one shot), and relevance ranking blended from text score, popularity, and
personalization — but it is explicitly *not* the system of record. It's a projection of the
metadata DB, kept eventually consistent through the same Kafka fanout (plus a separate update
topic for edits like artist renames). Hot queries are additionally cached in Redis with short TTLs
so identical high-frequency searches never reach the cluster. Remaining pressure is handled by
horizontal scaling and tuning analyzers/mappings to the domain's access patterns.

### Sharded relational source of truth with replicas and a cache front
Song/artist/album relationships are naturally relational, and strong consistency matters because
what gets indexed downstream must match the record of truth, so the metadata store is PostgreSQL —
horizontally sharded (by artist or song ID) with multiple read replicas per shard, reads hitting
replicas and writes hitting primaries. Redis in front absorbs the bulk of read traffic since hot
records repeat millions of times daily; invalidation is driven by the same Kafka upload/update
events. The article flags this service (alongside the CDN) as one of the two most critical
dependencies: remove the cache and replicas would drown, remove sharding and a single node caps
throughput.

### Cache-stampede defense
The residual risk of a cache-fronted hot store: if Redis vanishes, every dependent service falls
back to the database at once. Mitigations named: circuit breakers to stop cascade overload, and
staggering TTLs so entries don't expire in synchronized waves.

### Store-IDs-only playlists on a wide-column store
Playlist access is purely key-shaped: playlists by user ID, songs by playlist ID, membership
writes by playlist ID, sharing as a user↔playlist association. No read-time joins exist because
playlists store only song IDs; clients hydrate titles/artists separately from the metadata
service. That access shape plus heavy write volume and billions of rows makes Cassandra the pick
over a relational store: partition keys map one-to-one onto the queries, join support is
irrelevant, and replication factor 3 across availability zones keeps reads/writes alive through
node or zone loss, with tunable per-operation consistency. Trade-off: you give up joins and accept
application-side composition.

### Hot-partition mitigation by caching
Wide-column stores suffer when one key gets disproportionate traffic — e.g. an editorial playlist
followed by millions concentrates load on a single partition. The countermeasure is fronting hot
keys with Redis so most reads for popular items never touch the partition at all.

### Async event ingestion feeding offline ML, served from a cache
Behavioral signals (plays with duration and early-skip flags, playlist saves, repeated searches,
genre spread, users-who-played-X-also-played-Y co-occurrence) arrive at enormous volume — a
billion daily streams plus everything else. Writing them synchronously to a database would
throttle the user-facing path, so every interaction publishes to Kafka; workers drain into an
analytics store built for high write throughput and time-series shape (Cassandra or ClickHouse,
deliberately not PostgreSQL). An ML pipeline reads that store on an hourly/daily cadence,
recomputes recommendations offline, and writes results to Redis keyed by user. Serving is then a
single key lookup — among the cheapest operations in the system. The general pattern: absorb
firehose writes with a log, compute expensive results off the request path, serve precomputed
answers from a cache.

### Emergent resilience from stateless edge-cached chunks
Because segments are independently cached at edge nodes and served as plain HTTP, a listener
mid-song keeps receiving audio even if the metadata service, streaming service, or origin bucket
goes dark — the edge already holds the bytes. No failover machinery is written for this; it falls
out of the chunking + CDN design. This is the article's headline resilience lesson: prefer
architectures whose fault tolerance is a structural consequence rather than bolted-on logic.

### Cold-start cost of edge caching
First request for a never-streamed track misses the edge and triggers an origin fetch-and-fill,
so the first listener pays extra latency. Called out as an accepted trade-off for fresh uploads
rather than a problem to engineer away.

### Polyglot persistence — one datastore per access pattern
The closing selection table is itself a pattern: gateway (Kong / AWS API Gateway) for auth and
limiting, S3 for immutable blobs, CloudFront/Akamai absorbing ~80% of stream load, HLS as the
delivery protocol, Kafka for durable replayable fanout, Elasticsearch for text search, sharded
replicated PostgreSQL for relational truth, Cassandra for key-based high-write playlist data,
Redis at every hot-read seam, and Cassandra/ClickHouse for analytics. Each store earns its slot
by matching a specific read/write shape instead of one database serving all roles.

## Not absorbed

- Series branding ("High-Level Design Questions-Based Series #15") — interview-prep packaging,
  not engineering content.
- Closing sign-off line ("That's all, folks…" etc.) — farewell flourish, no substance.
- Timestamp, view count, and like/repost/reply numbers at the end of the capture — platform
  chrome scraped along with the post.
- Celebrity example queries (searching for specific artist names) — illustrative color for the
  fuzzy-search pattern, which is absorbed above without the examples.

## Fidelity check

**Post count in capture:** 1 (the entire article is one long-form post; no
`---AUTHOR-POST-BREAK---` separators present).

**Article outline (author's own section numbering):**
1. Requirements (functional + non-functional)
2. Capacity Estimation
3. API Gateway
4. Upload and Transcoding Pipeline
5. Streaming Service
6. Search Service
7. Metadata Service
8. Playlist Service
9. Recommendation Service
10. Full Data Flow Summary
11. Resilience and Fault Tolerance
12. Technology Choices Summary

**Pattern-to-section citations:**

| Pattern | Article section |
|---|---|
| Estimation-driven architecture | §2 Capacity Estimation |
| Gateway on the fast path only | §3 API Gateway |
| Direct-to-processor upload + transcoding pool | §4 Upload and Transcoding Pipeline (steps 1–2, bottlenecks) |
| Multi-bitrate encoding | §4 Upload and Transcoding Pipeline (step 2) |
| Chunked HTTP streaming (HLS) | §4 (step 2) and §5 Streaming Service (steps 2–3, protocol rationale) |
| DRM via encrypted chunks + signed URLs | §4 (step 2) and §5 (step 1) |
| Immutable blob storage | §4 Upload and Transcoding Pipeline (step 3) |
| Event-driven fanout over a durable log | §4 (steps 4–5), reinforced in §11 Resilience |
| Search index as derived projection | §6 Search Service |
| Sharded relational source of truth + cache front | §7 Metadata Service |
| Cache-stampede defense | §7 Metadata Service (bottlenecks) |
| Store-IDs-only playlists on wide-column store | §8 Playlist Service |
| Hot-partition mitigation by caching | §8 Playlist Service (bottlenecks) |
| Async ingestion → offline ML → cache serving | §9 Recommendation Service |
| Emergent resilience from edge-cached chunks | §5 (resilience property) and §11 Resilience and Fault Tolerance |
| Cold-start cost of edge caching | §5 Streaming Service (bottlenecks) |
| Polyglot persistence | §12 Technology Choices Summary |

Section 10 (Full Data Flow Summary) recaps flows already covered by the patterns above and
contributes no additional pattern of its own.
