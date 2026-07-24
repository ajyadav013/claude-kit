# Digest: Netflix Recommendation System — Machine Learning System Design

- **Source:** https://x.com/Harry_The_Nerd/status/2069785739810705773
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Engineering Articles
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Hybrid weighted recommendation mix

Rather than hard-bucketing users by content type (which walls each user into a silo and blocks
discovery), weight the recommendation blend by observed affinity — e.g., a heavy movie watcher
gets roughly a 70/15/15 split across movies, series, and documentaries. Use when a catalog spans
multiple content categories and you want affinity respected without eliminating cross-category
exposure. Trade-off: weights must be tuned and periodically refreshed, but the alternative
(strict bucketing) measurably harms long-term discovery.

### Recall and precision as the system's twin objectives

The whole architecture is organized around two ML metrics: recall (did the system surface things
the user would have enjoyed?) and precision (of what was shown, how much got real engagement?).
Each pipeline stage is deliberately assigned one of the two. This is a useful decomposition
whenever a single model can't optimize both cheaply — split the funnel so the wide stage chases
recall and the narrow stage chases precision.

### Back-of-envelope capacity estimation before design

Anchor the design on numbers first: 200M DAU, a 100K-title catalog, ~50 interaction events per
user per day at ~1KB each → ~10TB/day of raw behavioral data; ~2 sessions/user/day with one
homepage load each → ~400M recommendation requests/day, ~4,600 RPS average and ~10K RPS peak.
Storage math drives placement decisions: catalog metadata (~100MB) and item embeddings
(100K × 128 dims × 4 bytes ≈ 50MB) fit fully in memory; user embeddings
(200M × 128 × 4 bytes ≈ 100GB) need a distributed store (Redis/DynamoDB). The estimate is what
justifies later choices like precomputation and in-memory ANN.

### Precompute-and-cache to meet a hard latency budget

With a sub-200ms homepage target, live model inference per request is off the table. Instead,
each user's top-20 list is computed offline/asynchronously and written to Redis keyed by user id;
the request path is a single sub-millisecond MGET ("profile hydration"). Use whenever inference
cost exceeds the latency budget. Trade-off: recommendations are only as fresh as the last
pipeline run — which is exactly what the speed layer (below) compensates for.

### Cold-start strategy trio

Three complementary tactics for users with zero history:
1. **Explicit genre onboarding** — a handful of genre cards at signup, capped at 3–5 taps
   because form-like onboarding drives drop-off.
2. **Trending/popular content** — global and regional top lists plus well-known classics; social
   proof lowers decision fatigue for newcomers.
3. **Geo and device signals** — region strongly predicts content affinity (local-language
   catalogs), and device type at signup is a weak but usable prior.
The cold-start blend then decays gracefully: after a user finishes 2–3 titles, collaborative
filtering starts mixing in and personal signals take over.

### Rich behavioral signal taxonomy

Clicks alone are weak. The system ingests a layered signal set: session watch hours, completion
rate (finishing ~90% is strongly positive; abandoning early is negative), rewatches (among the
strongest affinity indicators), sparse-but-clean explicit thumbs ratings, search queries (direct
intent), watchlist adds without playback (interest with friction), time-of-day/device context
(mobile mornings → casual/short content; evening TV → long-form), and skip-intro/skip-recap
behavior (engagement depth). Weight signals by their reliability, not their volume.

### Embeddings as the core representation

Titles and users are encoded as dense vectors (typically 128–256 dimensions) so that semantic
similarity becomes geometric proximity — two crime dramas land near each other in vector space,
and recommendation reduces to nearest-neighbor search. Item embeddings (~50MB for 100K titles at
128 dims) live in memory; user embeddings (~100GB for 200M users) live in Redis/DynamoDB and are
refreshed on a cadence. The size asymmetry (items tiny, users huge) dictates the storage split.

### Three-service decomposition with Kafka decoupling

Behind the gateway/load balancer sit three services: a **User Service** (profiles; triggers
homepage hydration), a **Recommendation Service** (the two-stage ML pipeline), and a
**Data Aggregator Service** (consumes behavioral events and lands them in Cassandra). Kafka sits
on both seams — between User and Recommendation services so login spikes can't overload the
pipeline, and in front of Cassandra to buffer the high-throughput event stream.

### Two-stage pipeline: candidate picker then ranker

Scoring the full 100K-title catalog per request with one heavy model is infeasible at ~10K RPS
under 200ms, so the funnel splits:
- **Stage 1 — candidate picker (recall).** Approximate nearest-neighbor search (FAISS or
  Pinecone) over item embeddings narrows 100K titles to ~100 candidates in milliseconds;
  collaborative filtering ("watchers of X also watched Y") widens recall beyond the user's own
  history. Speed matters more than ordering quality here.
- **Stage 2 — ranker (precision).** A heavier neural model scores the 100 candidates with
  expensive features — watch history and affinity, content freshness, time/device context,
  thumbnail CTR among similar users, peer completion rates — and the top 20 land in Redis.
The trade-off is a two-model system to maintain, in exchange for tractable cost at each stage.

### Cassandra for the write-heavy behavioral data lake

All behavioral events are keyed by user id + timestamp and written to Cassandra, chosen because
the workload is write-dominant and time-series-shaped at ~10TB/day — the profile Cassandra is
built for. ML training reads from this lake.

### Lambda architecture for model freshness

Two problems: full retraining takes hours and can't run continuously, yet very recent behavior
should influence recommendations within minutes. The split:
- **Batch layer** — a nightly (every-24h) full retrain over the complete Cassandra dataset,
  recomputing all user and item embeddings; captures long-term and seasonal patterns.
- **Speed layer** — a lightweight model on the live Kafka stream applies incremental user-
  embedding updates, so a burst of thriller-watching shifts recommendations within minutes
  rather than after the next nightly run.
Batch buys depth and accuracy; speed buys responsiveness. Cost: two training paths to operate.

### Post-ranking diversity injection (anti-echo-chamber)

A pure precision ranker converges on serving one dominant genre, which suppresses discovery and
raises churn. A diversity layer between the ranker and the Redis write applies:
- **Category caps** — no genre may take more than 5–6 of the 20 slots.
- **Novelty slots** — 2–3 positions reserved for never-before-seen titles even at a slightly
  lower score.
- **Bandit-style exploration** — roughly 85% of slots exploit known preferences, 15% explore;
  engagement on exploration slots feeds back into the user embedding.
- **Shelf-based diversity** — the homepage is many horizontal shelves ("Because you watched…",
  regional trending, new releases, daily top-10), each with its own category rules; this attacks
  the echo chamber at both the UX and algorithmic level.
Trade-off: deliberately sacrificing some short-term precision for long-term engagement.

### End-to-end request/refresh loop

Request path: app open → gateway/LB → User Service → (Kafka event) → Recommendation Service →
Redis MGET of the precomputed top 20 → render shelves. Background path: session signals →
Data Aggregator → Kafka → Cassandra → nightly batch retrain plus real-time speed-layer updates →
candidate picker → ranker → diversity layer → Redis. The clean separation means the hot path
never touches the ML machinery.

## Not absorbed

- **Title/genre framing as an "ML System Design" walkthrough** — interview-prep genre framing;
  the design is a hypothetical exercise, not a first-hand account of Netflix's production stack.
- **Closing sign-off line** — casual farewell, no engineering content.
- **Engagement metadata in the capture** (view/like/repost counts, timestamp) — platform chrome,
  not article content.
- **"Technology Summary" section** — pure recap of tools already covered in earlier sections;
  its content is absorbed via the patterns above rather than as a separate pattern.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; capture JSON reports
  `postCount: 1`, no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline (author's section order):**
  1. Problem Statement
  2. Scale and Capacity Estimation (Traffic / Storage / Latency budget)
  3. Handling New Users: Cold Start Strategy
  4. Behavioral Signals
  5. What Are Embeddings?
  6. System Architecture: Three Core Services
  7. The Two-Stage ML Pipeline (Stage 1: Candidate Picker / Stage 2: Ranker)
  8. Profile Hydration
  9. Data Storage and Model Freshness: Lambda Architecture
  10. Diversity Injection: Avoiding the Echo Chamber
  11. End-to-End Request Flow
  12. Technology Summary
- **Pattern → source section mapping:**
  - Hybrid weighted recommendation mix → Problem Statement
  - Recall and precision as twin objectives → Problem Statement (reinforced in The Two-Stage ML
    Pipeline)
  - Back-of-envelope capacity estimation → Scale and Capacity Estimation
  - Precompute-and-cache for the latency budget → Scale and Capacity Estimation (latency budget)
    + Profile Hydration
  - Cold-start strategy trio → Handling New Users: Cold Start Strategy
  - Rich behavioral signal taxonomy → Behavioral Signals
  - Embeddings as the core representation → What Are Embeddings?
  - Three-service decomposition with Kafka decoupling → System Architecture: Three Core Services
  - Two-stage pipeline (candidate picker + ranker) → The Two-Stage ML Pipeline
  - Cassandra behavioral data lake → Behavioral Signals + Data Storage and Model Freshness
  - Lambda architecture for freshness → Data Storage and Model Freshness: Lambda Architecture
  - Post-ranking diversity injection → Diversity Injection: Avoiding the Echo Chamber
  - End-to-end request/refresh loop → End-to-End Request Flow
