# Digest: Design Netflix (HLD)

- **Source:** https://x.com/Harry_The_Nerd/status/2071256571028648283
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level system design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Read-dominated capacity framing drives an edge-first architecture
Before drawing any boxes, the article sizes the problem: 100M DAU x 150 min/day of viewing at an
average 10 Mbps works out to roughly 11 PB of video served daily, against a ~120 PB library
(~15,000 titles x ~1,200 variants x ~8 TB/title, ~9.7B stored objects). The conclusion is that the
hard problem here is egress bandwidth and startup latency, not write throughput — which justifies
pushing delivery to the edge and keeping the backend out of the video path entirely. The reusable
technique: identify the single dominant load dimension first and let it dictate the architecture's
center of gravity.

### Control plane / data plane separation at the gateway
The API gateway does auth, rate limiting, geo-based license enforcement, and regional routing —
but never touches a video chunk. All byte delivery happens edge-side with zero backend calls on
the hot path. Use this split whenever payload traffic dwarfs metadata traffic; the trade-off is
that the edge tier needs its own auth story (signed URLs, below) since the gateway can't gate it
per-request.

### GOP splitting as the parallelization primitive for media encoding
Video is cut into ~2-second groups of pictures, each an independently encodable unit. A 2-hour
film yields ~3,600 GOPs, and crossing that with ~1,200 output variants gives ~4.32M independent
encode tasks (and ultimately ~864,000 chunk files per title). Because no task depends on another
GOP's output, thousands of GPU workers can chew through the set concurrently — hours instead of
weeks. The general lesson: find the smallest self-contained unit of work in a heavyweight
pipeline and shard on it.

### DAG scheduler + three-queue resource manager for distributed batch work
Encode tasks are modeled as a DAG, flattened into a Kafka-backed task queue, and dispatched by a
resource manager that tracks three collections: pending tasks, idle workers, and running
task-worker pairs. The pool autoscales on queue depth; workers are specialized by media type
(video codecs on GPU instances, audio, subtitles). Worker crashes are absorbed by requeueing —
completed tasks are tracked so only unfinished work is redone. This is a clean template for any
embarrassingly parallel compute farm with heterogeneous worker types.

### Priority ordering inside the pipeline: streamable-first, best-codec-later
Two prioritization tricks avoid blocking availability on full completion. First, the opening GOPs
of every variant are encoded ahead of the rest, so a title (or episode 1 of a series) can go live
while the tail is still processing. Second, codecs are tiered: the widely compatible codec (H.264)
is encoded at high priority so the title is watchable within hours, while the slower,
better-compressing codec (AV1, ~30% better than H.265 but costlier to encode) fills in over the
following days. Trade-off: early viewers get worse compression; in exchange, time-to-available
drops from days to hours.

### Deterministic object naming eliminates lookup services
Chunks land in object storage under a fixed scheme — content id / variant id / chunk index — so
any component can compute the URL for any of the ~9.7B objects without consulting a database.
When the keyspace is fully derivable, spend zero infrastructure on resolving it. The cost is
rigidity: the path convention becomes a permanent contract (renaming means mass migration).

### Completion-event fanout via a message bus
When a title finishes encoding, one event on the bus triggers three independent consumers: a
metadata writer (DB + cache), a search indexer (Elasticsearch), and a manifest generator
(per-device-profile DASH manifests into object storage). New post-processing steps become new
consumers, not pipeline edits. Standard pub/sub fanout, applied at the ingestion/serving seam.

### Push-based private CDN inside ISP networks (Open Connect)
Instead of a pull-through third-party CDN, Netflix places its own appliances (OCAs, ~100-200 TB
SSD each) inside ISP data centers and exchanges. Differences from a reactive CDN: content is
pushed nightly during off-peak hours based on predicted regional demand, so popular titles are
resident before the first request; user traffic never crosses the public internet; the operator
fully controls placement; ISPs save transit cost, aligning incentives. A nightly placement
algorithm weighs regional viewing history, upcoming releases, per-appliance capacity, and
popularity decay for eviction. Constraint: edge storage is finite, so only the popular subset
lives there and eviction policy directly moves the cache-hit rate (~95% claimed).

### Proactive cache warming to absorb release-day thundering herds
For a big premiere, all episode chunks are pushed to edge appliances worldwide two days before
launch. When millions press play simultaneously, every request is already a cache hit — no cold
start, no origin fill storm. The pattern generalizes: when a demand spike is *scheduled*, pre-load
the cache instead of engineering the origin to survive the stampede.

### Tiered delivery with a long-tail fallback
Obscure titles that don't earn edge storage are served from a conventional CDN or straight from
object-storage origin. Accepting worse latency for rare requests keeps the premium edge tier
dedicated to the traffic that matters — a cost/perf tiering pattern for any skewed-popularity
catalog.

### Parallel entitlement checks with fail-fast rejection
Playback initiation runs three authorization checks concurrently — active subscription (via
cache), regional license, and device DRM certification — and rejects if any fails. Running
independent gates in parallel keeps the sub-2-second first-frame budget; the checks are
deliberately strongly consistent (entitlement/DRM) while everything else in the system tolerates
eventual consistency.

### Capability-based variant selection
The client declares device type, supported codecs, resolution, and audio capability at session
start; the server hands back only the variant subset that device can actually use (an old phone
gets H.264 capped at 1080p, a modern TV gets AV1 + HDR + Atmos). Negotiating capabilities once
per session, server-side, avoids shipping unusable options to constrained clients.

### Per-session signed manifests with template caching
Each play generates a personalized DASH manifest listing variant ladders and chunk-URL patterns
signed with a few-hour TTL bound to the user's session — so a cancelled account can't replay an
old manifest. Because signing thousands of URLs per session is the priciest part of initiation,
base manifests are cached per device profile and only the signing step is personalized. This is
the standard "expiring capability token" pattern for authorizing edge fetches without hitting the
backend per chunk.

### DRM as a separate key channel over encrypted-at-rest chunks
All stored chunks are encrypted; the manifest plus signed URLs let a client *fetch* bytes but not
*decrypt* them. A separate license service issues a session-bound decryption key (Widevine /
FairPlay / PlayReady per platform). Splitting transport authorization from decryption capability
means a leaked URL alone is worthless.

### Client-side adaptive bitrate as autonomous resilience
Quality decisions live entirely in the client: start at a conservative mid-tier, measure per-chunk
download speed, watch buffer depth, and switch variants seamlessly by fetching the next chunk from
a different ladder rung. No server participates, so degraded networks are handled with zero
backend load and no coordination latency. Trade-off: the server surrenders quality control to
heterogeneous client implementations.

### CMAF: encode once, serve every manifest dialect
Chunks are produced in a common media format compatible with both DASH (.mpd) and HLS (.m3u8)
clients; only the manifest differs per platform while the underlying chunk set is shared. This
halves (or better) storage and encode cost versus maintaining per-protocol chunk sets.

### Heartbeat-persisted playback position for resume
The client reports chunk index and position every 30 seconds into a durable session record;
resuming generates a manifest starting at the saved offset. Because position lives server-side
in a database, Continue Watching survives app crashes, device switches, and backend restarts.
The 30s cadence is the trade between write volume and how much progress a crash can lose.

### Dual-pipeline telemetry: streaming + batch off one event bus
Every client event (play/pause/seek, quality switch, buffer underrun, error, engagement) goes to
Kafka, partitioned by event type and user. Two consumers diverge: a Flink real-time path (seconds)
feeding live ops dashboards, regional anomaly detection — a buffering spike in one city implicates
a specific edge appliance — A/B metrics, and instant personalization triggers, landing in Redis;
and a Spark batch path (hourly/daily) producing recommendation training data, content-acquisition
analytics, and edge-placement optimization, landing in a Parquet data lake. Classic lambda-style
split: pay streaming complexity only for the use cases that need seconds-level freshness.

### Precomputed signal aggregates as the ML/serving interface
Per-user signals (genre histogram, completion rate, recent titles, preferred watch time) and
per-content signals (watch totals, completion and rewatch rates, watchlist adds) are maintained
as small Redis values, updated in near real time by the streaming pipeline. Downstream consumers
(ranking, edge placement) read cheap aggregates instead of raw event history — an anti-corruption
layer between the event firehose and the serving path.

### Two-stage recommendation: cheap candidate cut, expensive rank, cached result
Stage one prunes 15,000 titles to ~500 per-user candidates via collaborative filtering,
content-based similarity, and regional trending, as a periodic batch job. Stage two runs a neural
ranker over the candidates using user signals, time of day, device type, freshness, and
taste-neighbor popularity, writing the top 20 to Redis with a 6-hour TTL. Serving the home screen
is then one cache read. Compute is staggered — users likely to open the app soon are refreshed
first, active watchers are skipped — and a high-signal event (finishing a title) triggers an
immediate refresh instead of waiting for the schedule. The funnel shape (cheap filter, costly
rank, precomputed serve) is the canonical recipe for personalization at scale.

### Blended search ranking with asynchronous index sync
Search over a small catalog (~15K docs) mixes text relevance with popularity, per-user genre
affinity, hard regional-availability filtering, and a freshness boost. The index is kept current
by consuming the same content lifecycle topics as everything else; popularity fields sync
periodically from the batch pipeline rather than in real time, accepting staleness where it's
harmless.

### Notification frequency capping
Push/email fanout follows the usual bus-subscription model (release, episode-finished, watchlist
availability, re-engagement triggers), but delivery is throttled per user — at most one
promotional message per day no matter how many triggers fire — because over-notification drives
uninstalls. Rate-limit on the *user*, not the trigger source.

### Layered graceful degradation
Every tier has a documented fallback: edge appliance failure falls to a neighboring appliance or
CDN (brief quality dip, no stoppage); ranker failure serves raw candidates rather than an empty
home screen; cache-first reads mean the relational store failing degrades rather than outages;
the analytics pipelines are explicitly off the playback critical path so their failure is
invisible to viewers; queue durability means encode-worker crashes just requeue work. The design
stance: enumerate the failure of each component and pre-decide its degraded behavior.

### Mixed consistency budget
Strong consistency is reserved for the two places it's actually required — subscription
entitlement and DRM licensing — while recommendations, watchlists, metrics, and search freshness
run eventual. High-volume writes (watch history) are batched through the event bus instead of
synchronous inserts, and entitlement caching uses a minutes-level TTL tuned to catch
cancellations quickly without hammering the database.

## Not absorbed

- Series framing ("Questions-Based Series #21") and cross-references comparing this to the six
  previously designed systems (Twitter, Amazon) — interview-prep course scaffolding, not
  engineering content.
- The out-of-scope checklist (live streaming, downloads, billing, multi-profile, studio tools) —
  interview scoping convention; the one substantive aside (downloads ≈ pre-fetched streaming
  chunks) is noted here and needs no pattern.
- The closing sign-off and the captured engagement counters (views/likes/reposts) — post
  metadata, no content.
- Named show/release examples (a popular series premiere used to illustrate cache warming) —
  illustrative color; the underlying pattern is captured above without the branding.
- The "roughly 15% of global internet traffic" factoid — motivational stat restated only as
  context for the capacity section, not an actionable technique.

## Fidelity check

**Post count in capture:** 1 (single long-form article post; no `---AUTHOR-POST-BREAK---`
separators present).

**Article outline (author's own section ordering):**
1. Requirements (functional / out of scope / non-functional)
2. Capacity Estimation
3. API Gateway
4. Content Ingestion and Transcoding Pipeline (Stages 1–6, variants produced, bottlenecks)
5. Open Connect — Netflix's Custom CDN
6. Streaming Service (playback initiation Steps 1–7, bottlenecks)
7. Content Delivery — MPEG-DASH and ABR
8. User Profile Service
9. Metrics and Data Aggregation Service
10. Recommendation Service
11. Search Service
12. Notification Service
13. Full Data Flow Summary
14. Resilience and Fault Tolerance
15. Technology Choices Summary

**Pattern-to-section citations:**
- Read-dominated capacity framing → §1 (non-functional requirements) + §2 (Capacity Estimation)
- Control/data plane separation at gateway → §3 (API Gateway)
- GOP splitting → §4, Stage 1 (Preprocessor)
- DAG scheduler + three-queue resource manager → §4, Stages 2–4; failure behavior from §14
- Streamable-first / codec-tier prioritization → §4, Stage 2 + "Bottlenecks in the Transcoding
  Pipeline"
- Deterministic object naming → §4, Stage 5
- Completion-event fanout → §4, Stage 6
- Push-based private CDN → §5 (Open Connect, incl. placement strategy and bottlenecks)
- Proactive cache warming → §5 ("Proactive Cache Warming for New Releases") + §14
- Long-tail fallback tier → §5 (long-tail paragraph) + §13 (chunk delivery flow)
- Parallel entitlement checks → §6, Step 2
- Capability-based variant selection → §6, Step 3
- Signed manifests + template caching → §6, Step 4 + "Bottlenecks in the Streaming Service"
- DRM key-channel separation → §6, Step 5 + §15
- Client-side ABR → §6, Step 7 + §7 + §14
- CMAF shared chunks → §7 (DASH vs HLS)
- Heartbeat resume → §6, Step 6 + §13 (Continue Watching flow) + §14
- Dual-pipeline telemetry → §9 (ingestion architecture, real-time/batch pipelines)
- Precomputed signal aggregates → §9 (per-user / per-content aggregations)
- Two-stage recommendations → §10 (two-stage architecture, bottlenecks/staggering)
- Blended search ranking + async sync → §11
- Notification frequency capping → §12
- Layered graceful degradation → §14
- Mixed consistency budget → §1 (non-functional) + §8 (bottlenecks: batched history writes,
  entitlement cache TTL)
