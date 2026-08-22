---
source: https://netflixtechblog.com/pushy-to-the-limit-evolving-netflixs-websocket-proxy-for-the-future-b468bc0ff658
author: Netflix TechBlog
license-note: ideas absorbed in own words; no text or code reproduced
---

# Evolving a persistent-connection push proxy from best-effort to platform foundation

## What it teaches

Pushy is Netflix's WebSocket front door: devices hold long-lived connections
so backend services can push to them instead of devices polling. The article
covers how a service originally built for two use cases (voice-assistant
commands and killing TV-UI polling) grew to hundreds of millions of
concurrent connections and ~300k messages/second at five-nines delivery, and
which deliberate re-engineering steps made that possible: rewriting a
well-scoped stream-processing component onto the paved path, swapping a
manually-scaled registry store for a managed key-value abstraction,
connection-count-based autoscaling tuned against thundering-herd risk, and
then — once the foundation was stable — layering new products on it: direct
push with delivery acknowledgment, device-to-device messaging, and a
deliberately dumb transport protocol that let client teams build features
without proxy changes.

## Key patterns & decisions

- **Scale persistent-connection services on connection count, not CPU.**
  Parked WebSocket connections barely use CPU, so the usual CPU-based
  autoscaling signal is meaningless; Pushy scales on connections per node,
  with exponential scale-out the further past target the fleet drifts.
- **Periodic staggered reconnects as a load-balancing mechanism**: devices
  reconnect roughly every 30 minutes with jitter, giving the fleet a steady
  stream of rebalancing opportunities across instances.
- **Cap connections-per-node by thundering-herd math, not by maximum
  capacity**: bigger nodes mean fewer instances and lower cost, but every
  node death converts its whole connection count into a simultaneous
  reconnect storm. Netflix settled on ~200k connections/node average (400k
  headroom) as the balance point among CPU, memory, cost, and herd size.
- **Rewrite only well-scoped components**: the async message processor was
  rewritten from a fixed-size custom stream job to a standard autoscaled
  service only after maintenance burden grew — and the rewrite was judged
  acceptable because the component had a clear role, explicit success
  criteria, and paved-path tooling (canaries, automated rollouts) waiting on
  the other side. Post-rewrite it became zero-touch.
- **Move state to a storage abstraction instead of operating a store**: the
  connection registry migrated from a self-managed Redis-wrapper cluster
  (manual scaling pain) to the internal Key-Value abstraction service, buying
  autoscaling and low latency without owning the engine.
- **Silent-failure hygiene for long-lived connections**: added heartbeats,
  idle-connection cleanup, and better connection tracking because devices
  (especially older ones) drop connections without notice; fixing these edge
  cases is what pushed delivery reliability to 99.999%.
- **Direct push with status feedback vs. fire-and-forget queue**: bypassing
  the async queue and calling the specific proxy instance holding the target
  device's connection gives the sender an immediate delivery/failure signal
  it can act on (retry, fallback). Direct now carries the majority of
  traffic (~160k/s direct vs ~50k/s queued in a sampled day).
- **Device-to-device messaging via registry lookup + proxy-to-proxy hop**: a
  source device sends a message naming a target; the proxy consults the
  registry, forwards to the proxy holding the target's connection, and
  relays the delivery status back — the server-push path reused with a
  device as sender. An account-scoped device list service (fed by connection
  events over Kafka) provides discoverability and presence.
- **Be a dumb transport; let clients define application protocols**: the
  device-to-device envelope is a minimal generic message format; client
  teams layered their own app protocols on top and the platform needed
  almost no changes for two years of feature growth on it.
- **Cache hot-path lookups, measure the win**: caching the target-device
  allowlist and target-proxy location took median device-to-device round
  trip under 1 ms (p99 < 4 ms) and insulated the hot path from occasional
  registry-store latency spikes.
- **Edge security basics for device messaging**: authenticated connections
  only, rate limiting, and authorization checks that a device may target
  another device before any forwarding happens.
- **Event-loop discipline**: inbound message handling kicks off async work
  for validation/lookup/forwarding so registry calls never block the
  network event loop; rich metrics (cache hits, store calls, delivery rate,
  latency percentiles) drive alerts and tuning.

## When to apply / trade-offs

- The connection-count autoscaling + herd-bounded node sizing pattern applies
  to any long-lived-connection tier (WebSocket, SSE, MQTT); copying CPU-based
  policies from request/response services will misfire.
- Direct push trades the buffering/absorption of a queue for immediate
  feedback; senders must now handle failure signals themselves, which is
  precisely what some use cases want and others do not — Netflix keeps both
  paths.
- Generic transport protocols maximize platform-team leverage but push
  correctness concerns (versioning, semantics) to client teams; it worked
  here because the envelope was kept tiny and stable.
- The prototype-first culture note is load-bearing: hard problems were solved
  in a narrow game feature first, then generalized into the platform
  capability — the opposite order (build the general platform first) risks
  speculative design.

## Fidelity check

1. *Claim: Pushy is scaled on connections rather than CPU.* Capture explains
   CPU stays consistently low because most connections sit idle awaiting
   messages, so autoscaling keys on average connections per instance with
   exponential policies, unlike Netflix's CPU-bound edge proxies.
2. *Claim: node sizing was bounded by reconnect-storm risk.* Capture walks
   through the trade-off that a million-connection node would create a
   million-device simultaneous reconnect on failure, and lands on ~200k
   average / 400k max connections per node.
3. *Claim: direct push now dominates and provides delivery status.* Capture
   gives a recent 24-hour sample of roughly 160k direct vs 50k indirect
   messages/second and describes the direct path returning a status code the
   calling service can use to retry offline devices.
