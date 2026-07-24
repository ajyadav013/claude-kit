---
source: https://aws.amazon.com/compare/the-difference-between-throughput-and-latency/
author: AWS
license-note: ideas absorbed in own words; no text or code reproduced
---

# Latency and throughput: two orthogonal axes of network performance

## What it teaches

Latency and throughput are the two fundamental — and distinct — dials that
together define how "fast" a network (or any request-serving system) feels.
Latency is a per-operation delay: how long one piece of data takes to make the
trip, felt directly by an individual user. Throughput is aggregate carrying
capacity: how much data actually gets through per unit time, which caps how
many concurrent users or workloads the system can sustain. A system can be bad
at one and fine at the other; the worst combination (slow round-trips plus low
carrying capacity) produces congestion and a degraded user experience, while
the best combination (fast round-trips plus high capacity) feels responsive
under load.

The article also cleanly separates a third, often-conflated concept:
bandwidth. Bandwidth is the theoretical ceiling on data transfer for a link;
throughput is what you actually achieve against that ceiling once real-world
losses, retransmits, and topology get involved. High bandwidth is necessary
but not sufficient for high throughput.

## Key patterns & decisions

- **Latency vs throughput as independent axes** — treat delay-per-operation
  and volume-per-second as separate metrics with separate causes; optimizing
  one does not automatically fix the other, and both must be monitored to
  claim a system is healthy.
- **Bandwidth is a ceiling, throughput is the measurement** — never quote link
  capacity as delivered performance; measure what actually arrives, because
  packet loss, retransmission, and routing eat into the theoretical maximum.
- **Distinct measurement techniques per metric** — latency is probed with
  small round-trip pings (milliseconds, RTT); throughput is measured by moving
  a known volume and dividing by elapsed time, or with tooling that reports
  both together since each metric influences the other.
- **Root-cause taxonomy per metric** — latency degrades from physical distance
  (propagation), congestion-induced rerouting, protocol handshake overhead,
  and overloaded devices dropping/retransmitting; throughput degrades from
  bandwidth caps, insufficient processing power at network devices, packet
  loss forcing retransmits, and poorly designed topology with bottleneck
  paths. Diagnose against the right list.
- **Caching/CDN as a double win** — placing data geographically nearer to
  consumers shortens the trip (latency) *and* offloads the origin so it can
  serve more concurrent requests (throughput); one of the few levers that
  improves both axes simultaneously.
- **Transport-protocol selection as a trade-off knob** — a reliability-checking,
  connection-oriented protocol (TCP-style) accepts extra delay in exchange for
  guaranteed delivery, suiting file transfer; a fire-and-forget protocol
  (UDP-style) minimizes delay by skipping loss recovery, suiting streaming and
  gaming where a late packet is worthless anyway. Pick per workload, not
  globally.
- **QoS traffic classification** — divide traffic into priority classes so
  latency-sensitive flows jump the queue while bulk flows are shaped; an
  explicit admission that not all requests deserve equal treatment when
  capacity is contended.
- **Retransmission as the hidden coupling** — lost or delayed packets trigger
  retries, which add latency *and* burn capacity, so the two metrics drag each
  other down under stress; this feedback loop is why congestion collapse feels
  like both slowness and starvation at once.

## When to apply / trade-offs

- Apply the two-axis framing whenever writing SLOs or performance requirements:
  a p99 latency target and a sustained-requests-per-second target are separate
  commitments; hitting one says nothing about the other.
- Real-time workloads (streaming, IoT telemetry, interactive gaming, HPC) have
  hard floors on both metrics — check the workload's tolerance before choosing
  protocols or regions.
- The propagation lever (move data closer via caches, edge locations,
  regional deployment) is the cheapest latency fix but adds cache-invalidation
  and consistency complexity.
- Choosing a loss-tolerant transport buys delay reduction at the cost of
  delivery guarantees — only valid when stale/dropped data is acceptable.
- QoS prioritization is zero-sum under contention: someone's traffic is
  deliberately deprioritized, so it is a policy decision, not a pure
  optimization.
- The closing section is AWS product marketing (CloudFront, Direct Connect,
  Global Accelerator, Local Zones); the underlying patterns — CDN edge
  caching, private dedicated links, optimized routing over a managed backbone,
  and compute placed near users — generalize to any cloud or on-prem design.

## Fidelity check

1. **Claim:** latency and throughput mutually degrade each other rather than
   being fully independent in practice. **Support:** the capture states that a
   high-latency connection can exhibit lower throughput because data takes
   longer to arrive, and that low throughput can masquerade as high latency
   because large transfers complete slowly — hence the advice to monitor both.
2. **Claim:** bandwidth is the theoretical maximum while throughput is the
   realized figure. **Support:** the capture defines bandwidth as the
   theoretical maximum data volume transferable over the network and
   explicitly frames throughput as the actual amount transmitted given
   real-world limitations, noting high bandwidth alone does not guarantee good
   performance.
3. **Claim:** caching improves both metrics at once. **Support:** the capture
   explains that serving from a cache or CDN located nearer the user returns
   data faster (lower latency) and simultaneously reduces load on the origin
   source, letting it handle more concurrent requests (higher throughput).
