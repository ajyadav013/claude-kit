---
source: https://blog.algomaster.io/p/long-polling-vs-websockets
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Pushing server-initiated updates: long polling versus WebSockets

## What it teaches

Plain HTTP is client-driven: the client opens a request, the server answers,
the connection closes. Nothing in that model lets the server volunteer new
information, and its statelessness means every exchange starts from scratch.
Real-time products — chat, multiplayer games, live tickers — invert the
direction of initiative: the server has news before the client asks. The
article compares the two dominant workarounds and sketches when each earns
its keep.

**Long polling** is an upgrade over naive fixed-interval polling. Instead of
the client hammering the server every second, the client issues a request and
the server deliberately *withholds* the response — parking the request until
either fresh data exists or a timeout fires. Whichever happens, the client
immediately re-issues the request, forming a continuous loop. The result is
near-real-time delivery over completely ordinary HTTP.

**WebSockets** replace the loop with one persistent, bidirectional channel.
The client starts with a normal HTTP request carrying an upgrade header; if
the server agrees, the connection is promoted to the ws protocol and the
underlying TCP socket stays open. From then on either side can transmit at
any moment with no per-message handshake cost.

## Key patterns & decisions

- **Long polling as held-open request loop**: server parks the request until
  data or timeout, client re-requests instantly on every response — near
  real-time without any protocol beyond HTTP.
- **WebSocket upgrade handshake**: a standard HTTP request is promoted to a
  persistent full-duplex TCP channel, eliminating per-update connection setup.
- **Match transport to update frequency**: infrequent events (every few
  seconds/minutes) suit long polling; high-frequency or two-way traffic
  (collaborative editing, games) justifies WebSockets.
- **Firewall/proxy compatibility as a selection criterion**: long polling
  traverses restrictive middleboxes because it is indistinguishable from
  normal HTTP; WebSocket traffic can be blocked by older proxies and needs
  proxy-layer support (e.g. in the reverse proxy config).
- **Fallback abstraction layer**: libraries in the Socket.io mold expose one
  API and silently degrade from WebSockets to long polling when the
  environment can't upgrade — buying compatibility without dual code paths.
- **SSE as the one-way middle ground**: when the server only pushes and the
  client never streams back (feeds, notifications), server-sent events are
  simpler than full-duplex sockets.
- **Reconnection handling is the hidden WebSocket cost**: persistent
  connections shift complexity into error/reconnect logic and per-connection
  server memory at high concurrency.

## When to apply / trade-offs

- Long polling: simple systems, legacy or firewall-constrained environments,
  low-frequency notification streams. Costs: extra latency after each
  delivery (the loop must restart) and many concurrently parked requests
  consuming server resources at scale.
- WebSockets: sustained high-frequency, bidirectional exchange with many
  concurrent users. Costs: more moving parts (upgrade support end to end,
  reconnect logic), potential middlebox friction, and per-connection state on
  the server.
- MQTT sits outside the browser story: a lightweight pub/sub protocol favored
  in IoT where devices need minimal overhead.
- The decision reduces to four axes: implementation complexity, scalability
  under connection count, interaction shape (one-way vs two-way, sparse vs
  dense), and network environment tolerance.

## Fidelity check

1. Claim: long polling responds immediately when data arrives, otherwise
   returns empty at a deadline. Support: the capture describes the server
   holding the request open and replying at once on new data, or sending a
   minimal/empty response when the timeout is hit, after which the client
   re-requests.
2. Claim: WebSockets begin life as an HTTP request. Support: the capture
   walks through a handshake where the client sends an HTTP request with a
   websocket upgrade header and the server switches the connection from http
   to ws, keeping a TCP socket open afterward.
3. Claim: Socket.io-style libraries auto-degrade to long polling. Support:
   the capture's alternatives section states such libraries abstract over
   WebSockets and automatically fall back to long polling where WebSockets
   are unsupported, for cross-browser reliability.
