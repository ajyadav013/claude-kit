# Design YouTube — HLD digest

- **Source:** https://x.com/Harry_The_Nerd/status/2062909779576791167
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

The article walks through a YouTube-style video platform scoped to two flows — uploading and
streaming — deliberately excluding auth and social features (comments, likes, subscriptions).

## Patterns

### Back-of-the-envelope capacity sizing
Before drawing boxes, derive storage and throughput from a handful of assumptions: 5M daily
actives, 5 views per user per day (25M views/day), 10% of users uploading one video daily
(500K uploads/day), 300 MB average raw file, 1 GB cap per video. That yields ~150 TB/day of raw
ingest; transcoding into a ladder of renditions (360p through 1080p, optionally 4K) inflates
stored bytes roughly 3–4x, so plan for roughly 450–600 TB/day. On the read side, 25M daily views
works out to about 290 concurrent stream starts per second at peak — and because a CDN serves the
actual bytes, origin egress is a small fraction of total delivery. Use this discipline whenever a
design's feasibility hinges on data volume; the trade-off is that the numbers are only as good as
the input assumptions.

### Two loosely coupled pipelines joined by a message bus
Split the system into a video pipeline (upload, transcode, deliver) and a metadata pipeline
(structured records about each video), running in parallel and talking only asynchronously over
Kafka. Use this shape when heavy binary processing and lightweight structured state have very
different scaling and failure characteristics. Trade-off: eventual consistency between the two
sides and more moving parts than a monolithic write path.

### Presigned-URL direct-to-object-storage upload
The client asks the API tier for a short-lived presigned URL, then pushes the raw file straight
to object storage (S3) itself. API servers never touch the video bytes. Use this whenever
clients upload large blobs: piping gigabyte files through an application fleet wastes compute,
adds latency, and turns the API tier into a bottleneck. Trade-off: you give up an inline
inspection point at upload time and must validate/scan content asynchronously after landing.

### Object-storage event as the pipeline trigger
When the raw file lands, the storage service emits an object-created event that is forwarded onto
a Kafka topic; transcoding workers consume at their own pace. This makes ingestion fully
asynchronous: upload spikes queue up rather than flattening the transcoding fleet, and Kafka's
replay ability aids recovery. Use for any produce-fast/consume-slow boundary. Trade-off: end-to-end
latency becomes queue-depth dependent and you need monitoring on consumer lag.

### DAG-modeled transcoding with GoP chunking
Model per-video processing as a directed acyclic graph with three parallel branches — video work
(multi-resolution transcode, watermark, thumbnails, inspection), audio work (extract + encode),
and metadata work (parse + persist). First split the file into Groups of Pictures: short chunks
that decode independently, which buys two properties at once — chunks can be fanned out across
many workers in parallel, and a failed chunk can be retried without redoing the whole file. The
cluster is organized as six roles: a preprocessor (chunking + per-video DAG generation, chunks
parked in fast temporary storage), a DAG scheduler (explodes the graph into discrete tasks), a
resource manager (task/worker/running queues — the allocation brain), task workers (execute),
temporary storage (hands intermediates between stages, then discarded), and the encoded output
pushed to origin storage for CDN distribution. Use this pattern for any batch media/compute
pipeline where per-item work is decomposable. Trade-off: substantial orchestration machinery
versus a simple one-worker-per-video queue.

### Completion events instead of direct DB writes from workers
A finished transcode worker publishes to a Kafka completion topic; a dedicated handler service
consumes it and flips the video to available in the metadata DB and cache. Workers never write
the database directly. This keeps workers ignorant of storage schemas, makes retries a
consumer-side concern, and prevents a herd of workers hammering the DB during upload peaks. Use
wherever many ephemeral workers would otherwise share write access to a hot store. Trade-off: the
"available" flag is eventually consistent with actual completion.

### HLS chunked delivery with a manifest index
Store each rendition as small segments (2–10 seconds) and publish an M3U8 manifest that indexes
every chunk across every resolution. The player fetches the manifest first, then pulls chunks
sequentially, staying only a few segments ahead of the playhead — the full file is never
downloaded. Use for any long-form media delivery over plain HTTP. Trade-off: segmentation adds
packaging complexity and a manifest round-trip before first frame.

### Client-side adaptive bitrate switching
The player watches two signals — measured bandwidth and buffer health (seconds of pre-loaded
video) — and on its own picks which resolution's playlist to pull the next chunk from. The
manifest carries one playlist per rendition, so a quality switch is just changing which list the
client reads; no server-side coordination or event occurs. Use when clients have heterogeneous,
fluctuating networks. Trade-off: quality decisions are decentralized, so the server cannot
directly enforce a rendition policy per session.

### CDN edge caching for immutable video bytes
Video segments are static — identical bytes for every viewer — which makes them ideal CDN
content: a popular video cached at hundreds of edge nodes serves millions of plays without
touching origin. On an edge miss, the node pulls the chunk from origin and caches it for
subsequent viewers. The author's sharper point: without a CDN, a trending video produces an
origin thundering herd that horizontal scaling alone cannot cheaply absorb. The playback
request path is: play → API server → metadata from Redis/DB → client receives CDN + manifest
URLs → manifest, then chunks, fetched from the edge. Trade-off: CDN egress cost and cache-fill
latency on cold content.

### Key-value metadata store matched to the access pattern
Video metadata (title, description, uploader, CDN URL, processing status, timestamps) is looked
up almost exclusively by video ID — a pure key-value pattern — so a KV store like DynamoDB fits
directly; Cassandra is offered as the alternative when deployment must span geographies. The
underlying pattern: pick the database from the dominant access pattern, not from habit.
Trade-off: KV stores make ad-hoc secondary-attribute queries awkward.

### LFU (not LRU) eviction for popularity-skewed caches
Hot metadata lives in Redis, and because viewing is heavily skewed, caching roughly the top 20%
of videos by popularity captures the bulk of hits. Eviction policy matters: least-frequently-used
keeps a video that has drawn millions of views over several days resident, whereas
least-recently-used would evict it in favor of something touched once more recently. Choose LFU
whenever access frequency, not recency, predicts future demand. Trade-off: LFU adapts slowly when
popularity shifts abruptly (yesterday's viral video lingers).

## Not absorbed

- Series branding ("High-Level Design Questions-Based Series #14") — interview-prep framing, not
  engineering content.
- Closing sign-off line — conversational flourish only.
- Post timestamp and engagement counts (views/replies/reposts/likes) — platform metadata.
- Section 7 ("System Architecture Summary") — heading only in the capture, no body text; almost
  certainly an image/diagram the text render did not include, so nothing to absorb.
- Section 8 ("Key Design Decisions Summary") — a one-line-per-decision recap of material already
  covered above; absorbed only where it added rationale (nothing new beyond the sections).

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; `postCount: 1` in the JSON,
  no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline as authored:**
  1. Problem Scope (unnumbered lead section, with constraints/assumptions list)
  2. Back of the Envelope Estimation
  3. High Level Architecture Overview
  4. Video Upload Flow (Step 1: presigned URL; Step 2: pipeline trigger; Step 3: DAG
     transcoding; Step 4: completion + metadata update)
  5. Video Streaming Flow (HLS protocol; adaptive bitrate; hop-by-hop walkthrough; CDN
     importance)
  6. Data Layer (DynamoDB metadata store; Redis with LFU eviction)
  7. System Architecture Summary (heading only — no text captured)
  8. Key Design Decisions Summary
- **Pattern-to-section mapping:**
  - Back-of-the-envelope capacity sizing → sections 1 (Problem Scope constraints) and 2 (Back of
    the Envelope Estimation)
  - Two loosely coupled pipelines joined by a message bus → section 3 (High Level Architecture
    Overview)
  - Presigned-URL direct-to-object-storage upload → section 4, Step 1
  - Object-storage event as the pipeline trigger → section 4, Step 2
  - DAG-modeled transcoding with GoP chunking → section 4, Step 3
  - Completion events instead of direct DB writes → section 4, Step 4
  - HLS chunked delivery with a manifest index → section 5 (Streaming Protocol: HLS)
  - Client-side adaptive bitrate switching → section 5 (Adaptive Bitrate Streaming)
  - CDN edge caching for immutable video bytes → section 5 (Streaming Hop by Hop + Importance of
    CDN)
  - Key-value metadata store matched to the access pattern → section 6 (Metadata Database)
  - LFU eviction for popularity-skewed caches → section 6 (Caching: Redis with LFU Eviction)
