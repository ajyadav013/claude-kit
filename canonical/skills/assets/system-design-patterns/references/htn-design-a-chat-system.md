# Digest: Design A Chat System

- **Source:** https://x.com/Harry_The_Nerd/status/2061445321910284589
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Back-of-envelope capacity sizing before design

Derive infrastructure scale from a handful of assumptions before drawing boxes. The article works from 10M DAU × 50 messages/user/day → 500M messages/day → roughly 5,000 msg/sec; at ~100 bytes per text message that is ~500 KB/sec of write throughput and ~10,000 effective ops/sec once store+deliver are both counted. Concurrency is estimated at 20% of DAU online at once (~2M live sockets), which at ~50K connections per server yields a fleet of ~40 chat servers. Use this to justify every later technology choice; the trade-off is that the numbers are only as good as the assumed ratios, so treat them as order-of-magnitude anchors, not commitments.

### Persistent full-duplex connections (WebSockets) instead of polling

For server-initiated delivery, request/response HTTP is the wrong shape. Short polling at chat scale is ruinous (10M clients on a 5-second poll is ~2M req/sec of mostly-empty asks); long polling reduces waste but remains half-duplex and connection-churn heavy. A persistent bidirectional socket lets the server push the instant a message lands and lets the client send on the same channel. Cost: every live user pins a connection, so servers must be sized and load-balanced around connection counts (~50K per instance here), and connection state makes servers stateful.

### Store-and-forward: durably persist before attempting delivery

The invariant is write-first, deliver-second — a message is committed to the durable store (Cassandra here) before any delivery attempt, so a recipient device dying mid-push cannot lose it. Never optimistically skip the write to shave latency. The accepted trade-off is a small added delivery delay in exchange for a hard never-lose-messages guarantee; the article explicitly ranks slightly slower delivery above any risk of loss.

### Time-sortable distributed IDs (Snowflake) at ingest

The receiving chat server mints a Snowflake-style ID per message: globally unique without coordination, and roughly time-ordered so messages sort correctly across a distributed fleet. Assign it at the entry point so every downstream component (queue, store, receipts) shares one canonical identity and ordering key.

### Queue-decoupled write path with staged acknowledgements

The ingest server does minimal work — mint the ID, publish to Kafka, and immediately ack the sender ("one tick" = the system has custody). Delivery workers consume from Kafka, write durably to Cassandra, then handle routing. This decouples ingest latency from storage/delivery latency, absorbs bursts, and lets each stage scale independently. The receipt ladder maps to pipeline stages: accepted by the system (sent), acked by the recipient device over its socket (delivered), and read when the recipient opens the conversation and the client emits a read event that updates message status and notifies the sender.

### Offline branch: durable store + push notification + catch-up pull

If the presence check says the recipient is offline, nothing is lost because the message already sits in the store; the worker instead triggers a push notification, and when the recipient reconnects their client pulls the backlog from the message store and acks then. This turns offline delivery into a read-side catch-up problem rather than a retry-queue problem.

### Cross-server routing via a pub/sub bus keyed by user

With ~40 stateful socket servers, sender and recipient usually terminate on different instances. Each server subscribes to Redis Pub/Sub channels for its own connected users; a delivery worker publishes to the recipient's channel and whichever server holds that socket forwards it. This is lightweight and reuses infrastructure already in the stack, but it adds a network hop per cross-server delivery. The article flags that past this fleet size, deterministic routing (consistent hashing users to servers) or a service mesh becomes the better answer.

### Heartbeat + TTL presence with implicit offline detection

Clients ping every 5 seconds; the server refreshes a per-user Redis key (`presence:{userId}`) carrying the latest timestamp with a 15-second TTL. Miss three heartbeats and the key simply expires — the user goes offline with no explicit logout path, and "last seen" falls out for free as the final recorded heartbeat time. Trade-off: a disconnected user can look online for up to the TTL window (~15s); the article notes every major chat product accepts this inaccuracy.

### Polyglot persistence matched to access pattern

Each datastore is picked for one job: a wide-column store (Cassandra) for messages, Redis KV for presence (sub-ms reads, TTL expiry), Redis Pub/Sub for routing, Elasticsearch for search, and a SQL DB behind a Group service for membership. The Cassandra rationale is spelled out: the dominant query is "messages in conversation X, ordered by time, from offset Y," so partitioning by conversationId co-locates a chat's history on one node and clustering by timestamp makes range reads effectively constant-cost, while write throughput comfortably absorbs ~5,000 writes/sec.

### Group fan-out on write with a single stored copy

For groups (capped at 1024 members), the message is written once under the group's conversationId — never duplicated per member. A delivery worker expands the recipient list by fetching membership from the Group service, checks each member's presence, pushes to online members via the routing bus, and sends push notifications to offline ones. The cap is architectural: beyond ~1K members, per-member fan-out on write becomes a thundering herd, and the article prescribes switching to a hybrid — fan-out on read for very large groups, or a pub/sub tree for broadcast shapes.

### Out-of-band media: pre-signed upload + CDN delivery

Binaries never traverse the message pipeline. The client uploads directly to object storage (S3) using a pre-signed URL; the chat message carries only the media URL and metadata; recipients fetch from the CDN (CloudFront) edge, not from chat servers. This keeps socket servers free of large payloads and pushes bandwidth to edge infrastructure built for it.

### CDC-fed search index decoupled from the hot path

Full-text search is a separate read model: a change-data-capture pipeline tails message-store writes and asynchronously syncs them into Elasticsearch, and search queries hit a dedicated service. The point is isolation — Cassandra is not built for text search, and search load must never contend with real-time delivery. Cost: search results lag writes by the CDC pipeline's propagation delay.

### Edge authentication for socket upgrade + per-user send rate limiting

JWT validation happens at the load balancer / API gateway before the WebSocket upgrade completes (token in the upgrade request's header or query string), so unauthenticated connections never reach chat servers. Message sends are rate-limited per user — both an abuse control and back-pressure protection for the ingest queue against spikes.

### Naming the trade-offs explicitly

The design closes by enumerating its own weak points as deliberate choices: durability-before-delivery latency, the extra pub/sub hop and its scaling ceiling, the group-size fan-out cap, and the presence staleness window. The technique — stating each bottleneck alongside the mitigation you'd reach for at the next order of magnitude — is itself a reusable design-review habit.

## Not absorbed

- Series branding ("High-Level Design Questions-Based Series #13") — interview-prep packaging, not engineering content.
- Product name-drops as validation ("used by Facebook Messenger", "what WhatsApp/Messenger/Slack use") — appeal-to-precedent color; the underlying reasons are captured above instead.
- Closing sign-off ("That's all, folks…") — filler.
- View/like/reply counters and the post timestamp in the capture — platform metadata, not article content.

## Fidelity check

- **Post count in capture:** 1 (the whole article rendered as a single long-form post; `postCount: 1` in the JSON).
- **Article outline as authored:**
  1. Problem statement
  2. Requirements and scope (functional / non-functional / out of scope)
  3. Capacity estimation
  4. Protocol choice: WebSockets
  5. Core design: store-and-forward
  6. Write path (sender online) — with recipient-online, recipient-offline, and read-receipt sub-flows
  7. Cross-server message routing
  8. Online presence
  9. Database choices (incl. "Why Cassandra for messages specifically")
  10. Group chat
  11. Media handling
  12. Message search
  13. Auth and rate limiting
  14. Bottlenecks and trade-offs
  15. Sign-off
- **Pattern → section citations:**
  - Back-of-envelope capacity sizing — "Capacity estimation" (with fleet math repeated in "Protocol choice: WebSockets").
  - Persistent full-duplex connections — "Protocol choice: WebSockets".
  - Store-and-forward durable-write-first — "Core design: store-and-forward" and "Bottlenecks and trade-offs" (latency-vs-durability item).
  - Time-sortable distributed IDs — "Write path (sender online)", step 2.
  - Queue-decoupled write path with staged acks — "Write path (sender online)" including the recipient-online and read-receipt sub-flows.
  - Offline branch (store + push + catch-up pull) — "Write path", recipient-offline sub-flow.
  - Cross-server pub/sub routing — "Cross-server message routing" and the routing-complexity item under "Bottlenecks and trade-offs".
  - Heartbeat + TTL presence — "Online presence" and the presence-accuracy item under "Bottlenecks and trade-offs".
  - Polyglot persistence / Cassandra partitioning rationale — "Database choices".
  - Group fan-out on write, single copy, 1024 cap — "Group chat" and the fan-out-ceiling item under "Bottlenecks and trade-offs".
  - Out-of-band media via pre-signed URL + CDN — "Media handling".
  - CDC-fed search index — "Message search" (Elasticsearch also introduced in "Database choices").
  - Edge auth + rate limiting — "Auth and rate limiting".
  - Naming the trade-offs explicitly — "Bottlenecks and trade-offs".
