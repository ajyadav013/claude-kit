---
source: https://www.uber.com/en-IN/blog/ubers-next-gen-push-platform-on-grpc/
author: Uber Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Migrating a mobile push platform from SSE to gRPC bidirectional streaming

## What it teaches
Uber's real-time messaging layer (RAMEN) delivers state updates — driver positions,
ETAs, offers — to every mobile app. The first generation used Server-Sent Events over
HTTP/1.1: a one-way event stream plus a separate RPC endpoint where clients batched
acknowledgements every half minute. This article explains why that design hit a
ceiling and how the team swapped the transport for gRPC bidirectional streaming
(riding QUIC/HTTP3 via Cronet) without rewriting the backend business logic.

The deepest lesson is scoping: the migration was deliberately confined to the
protocol facade. Message storage, orchestration, connection lifecycle, and flow
control stayed in the existing Streamgate service, so the team could flip between
old and new stacks with low risk. A second, equally practical lesson is that the
rollout survived because they built an automatic client-side fallback from gRPC
back to SSE before going wide.

## Key patterns & decisions
- **Bidirectional stream replaces ack side-channel**: with SSE, delivery state was
  unknown for up to 30 seconds — fatal for messages (driver offers) that expire in
  30 seconds. In-stream acks make delivery confirmation instant, enable safe
  resends, expose per-message RTT, and let the server trim its retry queues sooner.
- **Facade-only protocol migration**: keep one backend runtime for both protocols;
  change only the transport edge. Avoids duplicating in-memory caches per user and
  keeps rollback trivial.
- **Separate frontend runtime per protocol**: the routing proxy tier got a parallel
  gRPC deployment that reuses the same shard-by-user sticky-routing layer, one
  channel per backend host, streaming and unary calls multiplexed on it.
- **Contract-first data modeling**: a protobuf schema defines request (sequence ids,
  message/feature acks, control messages) and response (payload, control, heartbeat)
  shapes, so every polyglot client implements the same behavior.
- **Stable public client interface**: the new mobile module preserved the old
  consumer-facing API, so feature teams needed zero migration work.
- **Compression to protect heartbeats**: >1MB uncompressed payloads on 2G/3G links
  starved the heartbeat and caused false disconnects; enabling gzip cut a 20-50s
  download to ~5s. gRPC delivers a message as a unit, unlike SSE chunked reads, so
  large payloads block harder.
- **Defensive stream handling**: serialize writes to a stream (the writer callback
  is not thread-safe), gate inbound traffic until the connection bootstrap message
  completes, keep a registry of open streams to cancel on shutdown, and check
  writability before every write so orphaned timer tasks (from missing termination
  callbacks) don't spin CPU forever.
- **Fallback tooling as a launch prerequisite**: detect gRPC connectivity failure on
  device and drop back to the SSE stack automatically; this repeatedly contained
  rollout incidents.
- **Buy-over-build transport decision**: hand-rolling an HTTP/2 client/server across
  many languages was judged to be re-inventing gRPC; reactive sockets were rejected
  for weak momentum; company-wide gRPC alignment reduced support cost.

## When to apply / trade-offs
- Reach for bidirectional streaming when acknowledgement latency is itself a product
  requirement (expiring offers, resend logic), not just for throughput.
- The facade-swap strategy applies to any protocol/transport migration on a stateful
  service: isolating the change to the edge preserves the cache/state layer and the
  rollback story.
- Head-of-line blocking does not vanish with gRPC: one connection still serializes
  large messages ahead of small ones. Uber's roadmap addresses this with multiple
  streams plus application-level prioritization, because HTTP/2 stream priority is
  effectively unimplemented in the wild.
- Wins reported: p95 connect latency improved by at least 45%, push success rates up
  1-2 percentage points across apps, and one consistent client implementation
  instead of several bespoke SSE parsers.

## Fidelity check
1. Claim: batched acks made delivery state stale for up to 30s, blocking resend of
   expiring offers. Capture support: the article states delivery state of a message
   is unknown for up to 30 seconds under the SSE design and that driver offers are
   valid for about that long, which prevented resending critical pushes.
2. Claim: missing gzip caused heartbeat-timeout disconnects on slow networks.
   Capture support: debugging showed >1MB payloads took 20-50 seconds on Edge/3G
   with compression off, starving heartbeats; after enabling gzip the same payloads
   arrived in roughly 5 seconds.
3. Claim: the backend kept a single runtime serving both protocols to avoid doubled
   state. Capture support: the team explicitly kept Streamgate as the backend for
   gRPC connections because a second runtime would duplicate per-user message and
   mailbox caches, doubling load and inviting inconsistency.
