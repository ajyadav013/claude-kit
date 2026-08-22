---
source: https://algomaster.io/learn/system-design-interviews/design-whatsapp
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Designing a WhatsApp-class messenger: push architecture, delivery guarantees, and fanout

## What it teaches

How real-time messaging inverts the normal web model: instead of clients pulling
data on request, the server must push each message the instant it arrives, which
mandates tens of millions of long-lived WebSocket connections and makes the
connection tier *stateful*. The chapter builds the design in three passes —
online-to-online delivery, offline catch-up, then group fanout — and then goes
deep on the machinery behind the familiar checkmarks: idempotent retries,
persist-before-ack, server-side ordering, TTL-based presence, and multi-device
sync. Target scale is 500M DAU, ~20B messages/day (~230K/s average, ~700K/s peak),
and ~50-100M concurrent sockets.

## Key patterns & decisions

- **Stateful chat tier + session directory** — a user's socket lives on exactly one
  chat server, so a Redis-backed session service maps user → server; cross-server
  delivery goes point-to-point (gRPC) or via a pub/sub backplane (Redis Pub/Sub or
  Kafka channels per-user) to avoid a full server mesh.
- **Persist before anything else** — every inbound message is durably written and
  assigned a server-side ID/timestamp *before* delivery is attempted and before the
  sender gets an ack, so a crash mid-flow never loses an acknowledged message.
- **Client retry + server dedup = effectively-once** — the client attaches a
  self-generated unique message ID and retries on timeout; the server treats a
  repeated ID as already-stored and re-acks, making sends idempotent.
- **Last-delivered watermark for offline catch-up** — rather than per-user mailboxes,
  each user carries a marker of the newest acknowledged message; on reconnect the
  server range-reads everything after the marker from the message store. The same
  mechanism doubles as multi-device sync.
- **No topic-per-user queues** — the active delivery/retry pipeline uses a small
  number of Kafka topics partitioned by recipient ID (per-user ordering preserved),
  because hundreds of millions of topics is untenable; the queue accelerates
  delivery while the database stays the source of truth.
- **Size-tiered group fanout** — small groups (under ~100 members) fan out directly
  from the sender's chat server; big groups route through a queue with parallel
  workers; deliveries are batched per destination chat server rather than
  per member.
- **Conversation-partitioned wide-column storage** — messages live in Cassandra
  keyed by a deterministic conversation ID (sorted-pair hash for 1:1, group ID for
  groups) with a time-ordered clustering key, plus a time bucket in the partition
  key to cap partition growth on chatty threads.
- **Denormalized conversation-list table** — per-user rows carry last-message
  preview and unread count so the home screen is one read; the cost is
  per-recipient write amplification (a 500-member group message can touch 500
  rows), mitigated by async/lazy updates.
- **Per-recipient receipts table** — group read/delivered state cannot live in one
  status column; a receipts table partitioned by message ID records each member's
  state, and the sender's UI aggregates it.
- **Server-authoritative ordering** — client clocks are never trusted; a
  time-encoded server ID orders each conversation, with optional per-conversation
  monotonic sequence numbers (single-writer per partition) only when gap detection
  is required; clients buffer and re-sort before display.
- **Presence via TTL heartbeats, queried lazily** — a Redis key with ~30s TTL
  refreshed by ~10s client heartbeats; status is fetched (and subscribed to) only
  for the chat currently on screen instead of broadcast to every contact.
- **Graceful drain for stateful servers** — deregister from the LB, refuse new
  handshakes, tell clients to reconnect elsewhere, wait out a drain window, then
  terminate; reconnecting clients recover pending messages via the watermark.

## When to apply / trade-offs

This is the reference blueprint for anything with long-lived push connections:
chat, collaborative editing presence, live dashboards, multiplayer signaling. The
core trade-offs: WebSockets buy the lowest latency but force session routing and
heartbeat/reconnect machinery (keep long polling as a fallback for hostile
proxies); SSE fits one-way feeds only. Write amplification (conversation-list and
receipt fanout) is deliberately accepted because reads dominate — but it justifies
group-size caps and lazy updates. Sequence-number ordering costs a single-writer
constraint, so reserve it for flows that truly need gap detection. E2E encryption
is a product decision that removes server-side search/moderation and complicates
multi-device key management.

## Fidelity check

1. *Claim:* durability is guaranteed by persisting before acknowledging.
   *Support:* the capture's delivery-guarantees section states the server must
   never ack until the message is in durable storage, since a crash between receipt
   and persistence would otherwise silently lose an acked message.
2. *Claim:* the design avoids one queue topic per user. *Support:* the offline
   handling section explicitly rejects per-user Kafka topics at 500M-user scale and
   instead uses a few partitioned topics keyed by recipient ID so each user's
   delivery tasks stay ordered.
3. *Claim:* group fanout strategy switches on group size. *Support:* the capture
   recommends direct sender-side fanout below roughly 100 members for latency and
   queue-based distributed fanout above that, calling the threshold a tunable
   parameter and noting a crash mid-fanout on a single server leaves partial
   delivery.
