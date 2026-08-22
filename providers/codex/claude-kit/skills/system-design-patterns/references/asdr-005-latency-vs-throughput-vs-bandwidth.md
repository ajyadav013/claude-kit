---
source: https://algomaster.io/learn/system-design/latency-vs-throughput
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Telling latency, throughput, and bandwidth apart before optimizing anything

## What it teaches
Three performance metrics that engineers routinely conflate actually describe
independent bottlenecks. Latency is per-request delay, throughput is realized
work volume per unit time, and bandwidth is the theoretical ceiling on data
transfer. Because each has different causes and different remedies, the first
diagnostic step in any performance effort is deciding which of the three is
actually the problem — otherwise you spend effort widening a dimension that
was never the constraint.

## Key patterns & decisions
- **Percentile latency reporting (p50/p95/p99/p99.9) instead of averages** — a
  mean can look healthy while a meaningful slice of users sits in a slow tail
  that the average completely hides.
- **Decompose latency into its four component delays** — propagation (physics
  of distance), transmission (bits onto the wire), processing (routers,
  balancers, servers), and queuing (waiting in busy buffers). Each component
  points to a different fix.
- **Throughput is gated by the slowest stage, not the widest one** — capacity
  upgrades anywhere except the bottleneck stage produce no gain; name the
  bottleneck before spending.
- **Bandwidth-delay product as the in-flight ceiling** — capacity times
  round-trip time tells you how much data can be in transit at once; if a
  transport window (e.g. TCP) is smaller than that product, a fast link still
  goes underused.
- **Little's Law linking the three knobs** — concurrency equals throughput
  times latency, so to push more work through you either raise parallelism or
  cut per-request time.
- **Accept the latency/throughput trade-off deliberately** — batching, queues,
  and pipelining raise aggregate volume while making each individual request
  slower; choose which side the product needs.
- **Round-trip elimination as the primary latency lever** — edge/CDN
  placement, multi-layer caching, connection reuse, and newer protocols
  (HTTP/2, HTTP/3) all attack the number or cost of round trips, which
  dominates once geography enters the picture.

## When to apply / trade-offs
- Use this taxonomy at the start of any "the service is slow" investigation:
  a single user complaining about slowness is a latency problem; the fleet
  saturating under load is a throughput problem; a bulk transfer crawling on
  a fat link may be a windowing/BDP problem, not a capacity one.
- Batching and async processing are throughput tools that actively hurt
  tail latency for interactive traffic — do not apply them on user-facing
  request paths without a latency budget.
- Bandwidth upgrades are the least frequently correct fix; realized
  throughput almost never reaches the link rating because of protocol
  overhead, loss, and processing limits.
- SLOs should be written against percentiles, and dashboards that show only
  averages should be treated as a defect.

## Fidelity check
1. Claim: averages hide the slow tail. Capture support: the chapter gives a
   concrete example of a system averaging 10ms while its p99 sits at 500ms,
   meaning one in a hundred users has a terrible experience the mean never
   reveals.
2. Claim: BDP caps usable bandwidth when windows are too small. Capture
   support: the worked example multiplies a 1 Gbps link (125 MB/s) by a
   100ms coast-to-coast latency to get 12.5 MB in flight, and notes a TCP
   window below that leaves link capacity unused.
3. Claim: physical distance sets a latency floor. Capture support: light in
   fiber moves at roughly 200,000 km/s, so a ~6,000 km trans-Atlantic hop
   costs about 30ms in propagation alone before any processing happens.
