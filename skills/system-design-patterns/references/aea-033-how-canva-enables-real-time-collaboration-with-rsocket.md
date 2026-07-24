---
source: https://www.canva.dev/blog/engineering/enabling-real-time-collaboration-with-rsocket/
author: Canva Engineering Blog
license-note: ideas absorbed in own words; no text or code reproduced
---

# Multiplexed bidirectional streaming at scale: Canva's RSocket-over-WebSocket gateway

## What it teaches
How to move a large product from request-response to soft-real-time push
(collaborative editing, live presentations) without giving every backend its
own socket to the browser. Canva concentrates all client connections in a
single WebSocket gateway, then layers RSocket on top so many logical channels
to many backends share one physical connection. Most of the article is the
operational fallout of that choice: per-channel backpressure as the primary
blast-radius control, reconnect discipline, streaming-aware observability,
connection-count autoscaling, channel-level (not connection-level) load
balancing via a service registry, and graceful connection draining during
deploys because long-lived connections defeat normal load-balancer
deregistration.

## Key patterns & decisions
- **Single WebSocket gateway with protocol multiplexing** — one client
  connection carries independent channels to many backends; the gateway also
  absorbs cross-cutting gateway duties (authn/z, tracing) and the pain of
  holding huge numbers of sockets.
- **Application protocol above the transport** — WebSocket alone cannot route
  messages to different services; RSocket supplies framed, stream-identified,
  transport-agnostic channel management on top.
- **Per-channel reactive backpressure as outage isolation** — a struggling
  backend simply stops signalling demand, so clients stop producing for that
  channel while every other channel keeps flowing; unlike circuit breakers,
  no error threshold has to trip first.
- **Per-channel backpressure policy selection** — non-critical streams (e.g.
  analytics) may buffer then drop, while user-action streams should fail fast;
  the strategy is chosen where the backpressure-aware stream is adapted into
  the frontend's non-backpressured reactive library.
- **Exponential backoff plus jitter on reconnect** — prevents a recovering
  gateway fleet from being flattened by a synchronized reconnection wave.
- **Streaming-specific error-rate metric** — request-based error rates don't
  apply to long-lived channels; approximate health as error frames over all
  frames excluding keepalives, and instrument both the transport and the
  responder layers.
- **Connection-count-first autoscaling** — mostly-idle connections consume
  memory, not CPU, so the primary scaling signal is open connections with CPU
  as secondary; naive load tests over-index on message volume and miss this.
- **Least-loaded balancing via a service registry** — the gateway connects
  directly to backend instances (a load balancer would hide new instances
  because so few backend connections exist); round-robin misallocates
  long-lived channels, so pick the least-loaded instance instead.
- **Application-driven connection draining on deploy** — load-balancer
  deregistration delay assumes requests finish naturally; long-lived
  connections don't, so a deregistration event triggers the app to close
  connections gradually, shifting clients to the new fleet without a spike.
- **MDC/log-context discipline for streams** — a channel outlives any single
  thread, so request-scoped logging context must be propagated explicitly or
  via the reactive framework's context pattern.

## When to apply / trade-offs
Apply when more than one backend needs server-push to the same clients — the
per-service-WebSocket approach dies at fleet scale. The gateway buys
isolation and shared infrastructure but becomes critical-path: it needs its
own careful scaling, draining, and registry-based balancing. Backpressure
end-to-end is the load-bearing feature; if your frontend reactive library
lacks it (as mainstream JS ones do), you must consciously decide, per stream,
what happens when the server can't keep up. For a single low-scale service, a
plain WebSocket with JSON frames is simpler and adequate.

## Fidelity check
1. Claim: RSocket rides on WebSocket because it is transport-agnostic framed
   streaming. Support: the capture states RSocket defines byte-level frame
   layouts carrying a stream ID, type, and payload, and runs over TCP or
   WebSockets given ordering guarantees.
2. Claim: backpressure beats circuit breaking for blast-radius control here.
   Support: the capture argues that a downed service simply stops requesting
   messages so clients stop producing, with no need to reach an error
   threshold or enter an error state as a circuit breaker would.
3. Claim: round-robin is wrong for long-lived channels. Support: the capture
   walks through a scenario where autoscaling adds a backend but round-robin
   keeps loading the already-overloaded older instances, concluding
   least-loaded selection suits long-lived channels.
