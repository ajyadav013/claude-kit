---
source: https://slack.engineering/real-time-messaging/
author: Slack Engineering (Sameera Thangudu)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Slack's real-time message fan-out architecture

## What it teaches
How Slack pushes millions of chat messages and state-change events per day to
tens of millions of persistently connected clients with ~500ms worldwide
delivery. The core design: a small set of specialized in-memory Java services
— stateful channel-owning servers sharded by consistent hashing, edge-located
gateway servers holding the websocket connections and subscriptions, stateless
admin servers bridging the web backend to the channel shards, and presence
servers tracking who's online. The write path is a two-stage fan-out: a
message lands on exactly one channel server (the shard owner), which forwards
to every gateway server subscribed to that channel worldwide, and each gateway
fans out to its locally connected clients. The architecture scales linearly
and degrades gracefully: shard replacement takes under 20 seconds and affects
only the few teams whose channels hashed there.

## Key patterns & decisions
- **Consistent-hash sharding of stateful in-memory servers**: every "channel"
  (a deliberately abstract ID covering users, teams, files, huddles, and real
  channels) hashes to exactly one channel server, which holds recent history
  in memory; roughly 16M channels per host at peak.
- **A dedicated ring-manager service (not the shards themselves) owns ring
  membership**: hash-ring managers detect unhealthy channel servers and swap
  in replacements in under 20s; consumers (admin and channel servers)
  discover current ring config through Consul service discovery.
- **Blast-radius dilution by spreading each tenant across all shards**: a
  team's channels scatter over every channel server, so losing one host means
  brief elevated latency for a slice of many teams rather than total outage
  for a few.
- **Two-tier fan-out (owner shard → subscribed gateways → local sockets)**:
  the channel server sends one copy per subscribed gateway region, and
  gateways do the last-mile multiplication to clients — keeping cross-region
  traffic proportional to gateways, not to users.
- **Only the connection-terminating tier is geo-distributed**: gateway
  servers deploy in multiple edge regions so clients connect nearby, with a
  drain mechanism shifting users from an unhealthy region to the nearest good
  one; the channel-owning tier stays centralized.
- **Connection bootstrap = fetch state over HTTP, then subscribe**: on
  connect, the gateway pulls the user's channel list from the web backend,
  sends an initial snapshot to the client, then asynchronously subscribes to
  the relevant channel-server shards; Envoy handles TLS termination and load
  balancing at the edge.
- **Everything is an event on one delivery spine**: hundreds of event types
  (reactions, bookmarks, membership changes) ride the same path as chat
  messages, so client state converges through a single mechanism.
- **Transient events skip persistence**: ephemeral signals like typing
  indicators enter via the client's websocket at the gateway and flow gateway
  → channel server → gateways without ever touching the database — a separate
  lighter path for data that has no value if delayed.
- **Presence as its own hashed service, viewport-scoped**: presence servers
  shard users independently, and clients (via the gateway as proxy) only
  subscribe to presence changes for users currently visible on screen —
  demand-side filtering to cap notification volume.

## When to apply / trade-offs
- This shape fits high fan-out, low-latency pub/sub where per-topic recent
  state matters (chat, collaborative docs, live dashboards). In-memory
  stateful shards buy speed at the cost of needing fast replacement machinery
  and accepting brief latency blips on failover.
- Consistent hashing plus an external ring manager trades a bit of extra
  infrastructure for sub-20s recovery; without spreading tenants across all
  shards, a single-shard loss would be a full outage for co-located tenants.
- Regional gateway deployment reduces client RTT but means the fan-out
  multiplier differs per region (observed to vary with team sizes) — capacity
  planning must be per-region, not global.
- Top-of-hour scheduled events (reminders, calendar posts) create regular
  traffic spikes; any similar system should expect synchronized-clock load
  and provision for it.
- Separating a non-persisted path for transient events avoids paying
  durability costs for signals whose value expires in seconds.

## Fidelity check
1. Claim: channel servers are consistent-hash-sharded and hold ~16M channels
   per host. Capture support: the article states each channel server maps to
   a subset of channels via consistent hashing and serves about 16 million
   channels per host at peak, with "channel" covering users, teams,
   enterprises, files, and huddles as well as regular channels.
2. Claim: shard replacement is fast and narrowly scoped. Capture support:
   the hash-ring managers (CHARMs) bring a replacement channel server into
   service in under 20 seconds, during which only users of the teams whose
   channels mapped to that host see elevated delivery latency.
3. Claim: typing indicators use a non-persisted delivery path. Capture
   support: the article describes transient events as a category never
   written to the database, flowing from the typing client's websocket
   through the gateway to the channel owner and back out to all subscribed
   gateways and clients.
