---
source: https://blog.algomaster.io/p/websockets
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# WebSockets: persistent full-duplex channels and when they beat request/response

## What it teaches

An introduction to the WebSocket protocol as the standard tool for real-time,
bidirectional client-server features. The core idea: instead of the client
opening a fresh connection for every exchange (HTTP) or repeatedly asking
"anything new?" (polling), both sides keep one TCP connection open and either
side can push data at any moment. The article walks the connection lifecycle,
contrasts WebSockets against plain HTTP, short polling, and long-polling,
lists the operational hazards of holding thousands of open connections, and
surveys the application classes where the pattern pays off.

## Key patterns & decisions

- **HTTP Upgrade handshake**: a WebSocket session begins life as an ordinary
  HTTP GET carrying an Upgrade header; the server answers with status 101
  ("switching protocols") and from then on the socket speaks WebSocket, not HTTP.
- **Frame-based messaging with tiny overhead**: after the handshake, messages
  travel as lightweight frames (headers can be as small as a couple of bytes),
  so per-message cost is far below a full HTTP request/response cycle.
- **Polling-vs-long-polling-vs-socket decision ladder**: short polling wastes
  requests that return nothing; long-polling holds a request open until data
  exists but still forces a reconnect per message and strains the server with
  connection churn; WebSockets remove both problems at the price of stateful
  connection management.
- **Heartbeats plus reconnection strategy**: because the whole model depends on
  one long-lived connection, production clients need ping/pong keepalives to
  detect dead links and an automatic reconnect policy for when the network drops.
- **Fallback transport for hostile networks**: some proxies and firewalls block
  the upgrade, so real deployments keep a long-polling (or similar) fallback path.
- **Horizontal scaling of stateful connections**: large fleets need load
  balancers and distributed socket servers, because each open connection pins
  server memory — a fundamentally different scaling problem than stateless HTTP.
- **Socket-specific security posture**: use the TLS variant (wss://),
  authenticate at connection time, and validate all inbound messages;
  cross-site WebSocket hijacking and DDoS are the named threat classes.

## When to apply / trade-offs

Reach for WebSockets when latency and server-initiated push matter: chat,
collaborative editing, live notifications, multiplayer game state, market-data
tickers, IoT command-and-telemetry, and interactive overlays on live streams
(the video itself usually rides other protocols). Stay with plain HTTP or
polling when updates are infrequent, ordering/statelessness simplicity matters
more than latency, or intermediaries in your network path are unfriendly to
long-lived upgraded connections. The trade is latency and bandwidth savings
against harder scaling (stateful connections), mandatory reconnect/heartbeat
machinery, and a wider security surface.

## Fidelity check

1. *Claim: the protocol switch is signaled by HTTP status 101.* The capture
   describes the client sending a GET with an Upgrade header set to
   "websocket" and the server replying with a 101 code that changes the
   protocol for the rest of the connection.
2. *Claim: frame overhead can be as low as ~2 bytes.* The capture's "lower
   overhead" bullet states that post-handshake frames carry headers as small
   as two bytes, cutting transferred data versus HTTP.
3. *Claim: long-polling reduces request frequency but risks server resource
   exhaustion.* The comparison section says long-polling holds connections
   open until data or timeout, forcing a new request per message, and that
   managing many open, frequently-reconnecting connections can exhaust server
   resources.
