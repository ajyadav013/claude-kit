# Digest: Design A News-Feed System

- **Source:** https://x.com/Harry_The_Nerd/status/2058553384735842654
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (High-Level Design series, entry #12)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

The article walks through designing a follow-based social feed (Facebook/Inshorts style):
users publish posts and read a personalized, time-ordered feed assembled from the accounts
they follow. Two endpoints anchor the design — a post-creation write API and a feed-read API —
with targets of 10M DAU, high availability, low-latency reads, and eventual consistency
tolerated on delivery.

## Patterns

### Back-of-the-envelope capacity estimation
Before picking any architecture, derive rough load numbers from the stated scale. The article
works from 10M DAU with a 10:1 read-to-write ratio and ~200 KB average post size (image URLs
included), landing on roughly 60 writes/sec, 580 reads/sec, ~600 GB of new data per day, and
~2.3 GB/sec of read bandwidth. The point of the exercise is that the numbers themselves dictate
decisions: read volume this lopsided makes an aggressive caching layer mandatory rather than
optional. Use this whenever sizing a system; the trade-off is that the estimates are crude, but
they only need to be order-of-magnitude correct to steer the design.

### Fan-out on write (push model)
At publish time, insert the new post's ID into a precomputed per-follower feed cache — one cache
write per follower. Readers then get an already-assembled feed straight from cache, so read
latency is excellent. The failure mode is the hotkey/celebrity problem: an account with, say,
100M followers triggers that many cache writes in a burst. Use it when follower counts are
modest and read latency dominates; avoid it as the sole strategy when a few accounts have huge
audiences.

### Fan-out on read (pull model)
Defer the work to read time: when a user opens their feed, query recent posts from every account
they follow and merge on the fly. Writes become trivially cheap, but each read turns into a wide
database fan-out — at ~580 reads/sec against ~500 followed accounts each, the query amplification
is severe. Use it when write amplification is the bigger risk (high-follower authors) or when
feeds are read rarely relative to how often they'd be updated.

### Hybrid fan-out
The production-grade compromise used by large social platforms: push (fan-out on write) for
ordinary accounts, pull (fan-out on read) for high-follower accounts, merging the two at read
time. This caps write amplification at the celebrity end while keeping reads fast for the common
case. The article notes the split matters less for a news product with few celebrity-scale
accounts, but is the right answer for a general-purpose network.

### Chronological feed via Redis sorted sets
Store each user's feed as a Redis sorted set keyed per user (e.g. `UserFeed:{userId}`) with the
post timestamp as the score. Inserts are O(log n) and reads come back already ordered, which
gives a chronological feed for free — no ranking model needed for a recency-first product. The
trade-off is memory cost per user and the need for explicit retention trimming (below).

### Asynchronous write path via an event log
The write path decouples post persistence from feed delivery: the post service persists to the
post store and post cache, then emits an event to Kafka. Downstream fan-out workers consume
asynchronously, look up the author's followers in a graph store, and insert the post ID into
each follower's sorted-set feed. A notification service consumes the same events to send push
alerts. This keeps the user-facing write fast and lets fan-out throughput scale independently;
the cost is a delivery delay (see feed staleness below).

### Read path with ID hydration and cache backfill
Feed reads fetch a list of post IDs from the per-user feed cache, then hydrate each ID into full
content from a separate post cache. On a miss, fall back to the post database and refill the
cache. Storing IDs (not bodies) in the feed structure and hydrating at read time avoids
duplicating full post content across every follower's feed.

### Polyglot persistence — match each store to its access pattern
The design uses four storage roles rather than one database: a write-optimized NoSQL store
(Cassandra-class) for post bodies, a graph database or adjacency-list store for
follower/following traversal, Redis sorted sets for feed ordering, and a plain Redis cache for
fast post hydration. The trade-off is operational surface area — four systems to run — in
exchange for each workload hitting a store shaped for it.

### Media via object storage + CDN
Never serve binary media from the post database — at ~2.3 GB/sec of read traffic it would
collapse. Media lives in an object store (S3-class) and is delivered through a CDN; the post
record holds only the URL. Cache-control headers keep images pinned at edge nodes near users,
cutting both origin load and latency.

### Load balancing every service tier
Place a load balancer between the gateway and each downstream microservice (post service, feed
read service, fan-out workers, notification service) so any tier scales horizontally and no
single instance is a choke point. Health checks at the balancer route around failed instances
automatically.

### Cursor-based pagination
Feed responses page with a cursor — the timestamp of the last item returned — rather than a
numeric offset. Offsets degrade as the feed deepens, while a cursor lets the read service resume
the sorted-set scan from that score in O(log n) regardless of feed length. Each response carries
the next cursor for the client to echo back.

### Kafka partitioning by author for ordered, scalable fan-out
Partition the post-event topic by the author's user ID so all of one author's events stay on one
partition and retain their order. Fan-out workers form a consumer group, each owning one or more
partitions, and scale horizontally as write volume grows; partitions can be added later without
downtime. The trade-off of key-based partitioning is that a single hyperactive author is bounded
by one partition's throughput.

### Bounded cache retention with a database of record
Redis memory is finite, so each feed sorted set is capped at the newest 1000 post IDs; after each
insert the worker trims overflow with a rank-range removal (ZREMRANGEBYRANK). Reads for anything
older fall through to the post database, which remains the authoritative full history. This is
the general pattern of a size-bounded hot cache in front of a durable cold store.

### Gateway-level auth and asymmetric rate limiting
Authenticate with JWTs at the API gateway so every request is validated before touching any
backend. Rate-limit there too, but asymmetrically: write endpoints get tight per-user throttles
(protecting Kafka from ingest spikes and abuse), while read endpoints get looser but still
bounded limits to shield the feed-read service.

### Search decoupled via CDC into Elasticsearch
Keep search entirely off the feed hot path: a change-data-capture pipeline asynchronously syncs
new posts from the post database into a dedicated Elasticsearch cluster, and a separate search
service queries it. Feed reads and writes never touch the search index; the cost is search
results lagging writes slightly.

### Named trade-offs: celebrity herd, staleness, memory
The closing section makes the compromises explicit: (1) write-side fan-out from a huge-follower
account causes a thundering herd — tolerable for a news product with few such accounts, solved
by the hybrid model otherwise; (2) async fan-out means a short gap between publish and feed
appearance, acceptable under eventual consistency; (3) keeping only IDs in per-user feeds keeps
Redis memory manageable, deferring full content to hydration time.

## Not absorbed

- **Series framing** ("High-Level Design Questions-Based Series #12") — interview-prep packaging, not engineering content.
- **Sign-off line** ("That's all folks…") — conversational close, no substance.
- **Second post** ("Reposts appreciated hehe") — engagement solicitation only.
- **Engagement metrics** (views/likes/repost counts in the capture) — platform chrome, not article content.

## Fidelity check

**Post count in capture:** 2 (the article post + a one-line repost request).

**Article outline (as authored):**
1. Problem statement
2. Requirements and scope (functional / non-functional)
3. Back-Of-The-Envelope Estimation
4. Core design decisions — Fan-out on Write & Fan-out on Read (Hybrid model), with subsections: Fan-out on Write (Push Model), Fan-out on Read (Pull Model), The Safe Spot (Hybrid), Chronological ordering
5. Write path
6. Read path
7. Database choices
8. CDN for media
9. Load balancing
10. Feed pagination
11. Kafka scalability
12. Data retention in Redis
13. Auth and rate limiting
14. Search
15. Bottlenecks and trade-offs
16. Sign-off

**Pattern → section mapping:**

| Pattern | Article section |
|---|---|
| Back-of-the-envelope capacity estimation | Back-Of-The-Envelope Estimation (§3) |
| Fan-out on write (push model) | Core design decisions → Fan-out on Write (§4) |
| Fan-out on read (pull model) | Core design decisions → Fan-out on Read (§4) |
| Hybrid fan-out | Core design decisions → The Safe Spot (Hybrid) (§4) |
| Chronological feed via Redis sorted sets | Core design decisions → Chronological ordering (§4) |
| Asynchronous write path via an event log | Write path (§5) |
| Read path with ID hydration and cache backfill | Read path (§6) |
| Polyglot persistence | Database choices (§7) |
| Media via object storage + CDN | CDN for media (§8) |
| Load balancing every service tier | Load balancing (§9) |
| Cursor-based pagination | Feed pagination (§10) |
| Kafka partitioning by author | Kafka scalability (§11) |
| Bounded cache retention with a database of record | Data retention in Redis (§12) |
| Gateway-level auth and asymmetric rate limiting | Auth and rate limiting (§13) |
| Search decoupled via CDC into Elasticsearch | Search (§14) |
| Named trade-offs: celebrity herd, staleness, memory | Bottlenecks and trade-offs (§15) |
