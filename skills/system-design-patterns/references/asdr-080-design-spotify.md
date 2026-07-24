---
source: https://algomaster.io/learn/system-design-interviews/design-spotify
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Designing a Spotify-class music streamer: signed-URL control plane, CDN data plane, polyglot storage

## What it teaches

How to structure an extreme read-heavy media platform (200M DAU, ~1B streams/day,
~5 PB/day of audio egress) so the API tier never carries the bytes. The keystone
move is separating the control plane — a lightweight authorization call that
returns a short-lived signed CDN URL — from the data plane, where clients pull
chunked, multi-bitrate, DRM-protected audio straight from edge caches. Around that
core the chapter assembles search (Elasticsearch with typo tolerance and layered
ranking), playlists, a batch-plus-realtime recommendation stack, polyglot storage
choices, multi-layer caching, graceful degradation priorities, and the royalty /
fraud pipeline that turns playback events into money.

## Key patterns & decisions

- **Signed, expiring CDN URLs as the streaming handoff** — the playback service
  checks subscription tier, region licensing, and rate limits, then mints a
  user-bound URL valid ~15-30 minutes; audio bytes never transit the app servers.
- **Transcode → chunk → encrypt ingestion ladder** — each track is stored at
  multiple bitrates (roughly 24-320 kbps), split into 5-10 second chunks, and
  DRM-encrypted; chunking enables fast start, cheap seeking, per-chunk caching, and
  quality switches at chunk boundaries (HLS/DASH manifest model, recommended over
  progressive download).
- **Power-law-aware CDN strategy** — the top sliver of the catalog serves the vast
  majority of streams, so edge caching is exceptionally effective; warm caches by
  pre-pushing anticipated releases, tracking trending velocity, prefetching a
  playlist's upcoming tracks, and regionalizing by taste; audio chunks are marked
  immutable with long TTLs.
- **Polyglot persistence mapped to access pattern** — relational store with read
  replicas for the slowly-changing, join-heavy catalog; Elasticsearch for text;
  Cassandra partitioned by user for playlists and by user+time for the
  firehose-scale listening history; Redis for sessions and precomputed
  recommendations. No sharding where a single well-indexed primary suffices.
- **Search as a separate denormalized index** — fuzzy matching, phonetic analyzers,
  and edge n-grams for autocomplete; ranking blends text relevance with popularity,
  personal listening affinity, and a small recency boost; hot queries are cached
  ahead of the index.
- **Precompute-then-serve recommendations** — heavy collaborative-filtering /
  content-embedding models run offline (weekly or daily batch) and park results in
  Redis; only lightweight seed-based or next-track inference happens at request
  time via a feature store; an ensemble shifts weight toward content signals for
  cold-start users.
- **Degradation ordering with one hard invariant** — every auxiliary feature
  (recommendations, search, playlist edits) has a canned fallback, but playback
  must survive; recommendation failure serves generic hits, search failure shows
  recents, playlist failure goes read-only.
- **Stream-counting integrity pipeline** — playback events batch into Kafka, a
  stream processor reconstructs sessions and applies the 30-second industry
  threshold for a billable stream, ML fraud filters strip loops/bot farms/
  geo-impossible plays before royalty aggregation.
- **Offline downloads as leased content** — device-bound encrypted licenses expire
  after ~30 days offline and renew against the subscription; per-account device and
  download caps bound abuse.

## When to apply / trade-offs

The signed-URL control/data split generalizes to any large-object delivery: video,
podcasts, file distribution, model weights. Use it whenever egress volume dwarfs
what an application tier should proxy. The precompute-recommendations pattern
applies wherever ML quality matters more than freshness — accept hours-stale
output to afford richer models, and reserve real-time inference for
session-contextual features. Polyglot storage buys per-workload performance at the
price of operational surface area; the chapter implicitly argues you earn each
extra database by a distinct access pattern (write-heavy time series vs.
relational catalog vs. text search). DRM and the 30-second stream threshold show
business/legal constraints shaping architecture as much as scale does.

## Fidelity check

1. *Claim:* audio delivery deliberately bypasses the API servers. *Support:* the
   capture's streaming flow has the client exchange an authorized request for a
   signed URL and then fetch audio directly from a CDN edge, explicitly noting the
   separation is what lets billions of streams scale without the API tier becoming
   the bottleneck.
2. *Claim:* consumption follows an extreme power law that makes edge caching cheap.
   *Support:* the CDN section states roughly the top 1% of songs generate about 90%
   of streams and the top 10% cover over 99%, leaving a long tail that can stay at
   origin.
3. *Claim:* not every play is a royalty-bearing stream. *Support:* the royalty
   section describes a 30-second minimum-play industry threshold, bot/loop
   filtering (e.g., the same track replayed hundreds of times, or geographically
   impossible session jumps), and monthly pool-based payout computed from each
   artist's share of valid streams.
