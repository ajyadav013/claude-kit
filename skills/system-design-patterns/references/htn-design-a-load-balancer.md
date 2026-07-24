# Digest: Design a Load Balancer

- **Source:** https://x.com/Harry_The_Nerd/status/2046465659551576395
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

The article walks through a system-design exercise: build a load balancer able to handle an
assumed 1M requests/second, covering routing layers, distribution algorithms, health checking,
TLS handling, session affinity, dynamic configuration, and the (deliberately thin) data layer.

## Patterns

### L4 vs L7 routing split
Transport-layer (L4) balancing forwards purely on IP + TCP/UDP port without opening the payload,
so it is extremely fast; application-layer (L7) balancing parses the HTTP request and can steer
on path, header, or cookie (e.g. an API pool, an image pool, a payments pool per path prefix).
Trade-off: L7 buys routing intelligence at the cost of per-request parsing overhead. The stated
production norm is L7 for application traffic and L4 where raw throughput matters.

### Virtual IP (VIP) as the single entry point
Redundant balancer nodes still need to present one stable address to clients. A floating virtual
IP fronts the whole node group; when the node currently holding it dies, the address migrates to
a surviving node with no client-visible change. DNS round-robin (multiple A records rotated) is
the simpler alternative, but VIP failover is faster and more dependable, so the article prefers
it for production.

### Round robin
Cycle through the server list in fixed order — effectively an index computed as a counter modulo
the pool size, incremented per request. Appropriate when every backend has identical capacity;
it ignores both machine specs and in-flight work.

### Weighted round robin
Round robin plus a per-server weight proportional to hardware capacity, so a box with 32 GB RAM
and 16 cores absorbs correspondingly more traffic than an 8 GB / 4-core one. The fit is a
heterogeneous fleet where equal shares would overload the small machines.

### IP hashing
Pick the backend as hash(client IP) modulo pool size. Because the mapping is deterministic, a
given client keeps landing on the same server — affinity for free, with no external session
store. Two failure modes: many clients behind one NAT collapse onto a single backend (skewed
load), and any change in pool size reshuffles nearly all mappings.

### Consistent hashing
Fixes the reshuffle problem of modulo hashing. Servers occupy points on a conceptual ring
(the article illustrates positions 90/180/270 on a 0–360 ring); a request hashes to a ring
position and walks clockwise to the first server. Removing one node remaps only the arc between
it and its predecessor — roughly 1/N of traffic — leaving everything else untouched. The article
cites Cassandra, Redis Cluster, and CDNs as real users of this scheme.

### Least connections
Send each new request to whichever backend currently has the fewest open connections. This is
the right choice when request cost varies wildly (10 ms vs 10 s in the article's example):
order-based schemes can stack slow requests on one unlucky machine, whereas connection counting
tracks actual load.

### Dual health checking (active + passive)
Active checks: the balancer probes every backend on a short interval and pulls a server from
rotation the moment a probe times out. Passive checks: the balancer observes live traffic and
ejects a server that returns too many errors or timeouts. They cover different failure shapes —
active detects fully silent hosts, passive detects hosts that answer but answer badly — so
production systems run both.

### SSL termination at the edge
HTTPS is decrypted once at the balancer; backends receive plain HTTP. Certificates live only on
the balancer tier instead of on every server, and the fleet is spared the aggregate crypto CPU
cost. Implicit trade-off: traffic behind the balancer is unencrypted, and the edge becomes the
certificate management point.

### Shared session affinity via Redis
When multiple balancer nodes exist, per-node memory cannot hold sticky-session state — user X
may arrive at node 1 now and node 2 next. All balancer nodes read/write a common Redis cluster
mapping user → assigned backend, so any node makes the same routing decision. Needed for
stateful applications where mid-session server switches break things.

### Watch-based dynamic config (Zookeeper)
Routing policy — which algorithm per pool, server weights, health-check intervals, certificate
locations — lives in a central coordination store. Balancer nodes subscribe to change
notifications and apply updates live, with no restart. Zookeeper is the article's pick for this
role.

### Infrastructure-shaped data layer (no primary database)
The design's storage is coordination and telemetry, not business records: Zookeeper for config,
Redis for session mappings plus shared backend-health state, and a time-series store
(InfluxDB/Prometheus) for req/s, latency, error-rate, and distribution metrics feeding Grafana
dashboards. The author flags the absence of any SQL/NoSQL business database as the design's
distinguishing property versus typical HLD answers.

### Horizontal balancer tier + graceful degradation
At 1M req/s a single balancer node is itself the bottleneck, so the balancer scales out
horizontally behind the VIP, with Redis and Zookeeper keeping the nodes coherent. Latency
discipline: the routing decision must stay in-memory (config cached locally, health state in
Redis) and add under 1 ms per request, because the balancer sits on every request's critical
path. Availability comes from the VIP failover plus health checks steadily shrinking — never
zeroing — the usable pool as backends fail.

## Not absorbed

- Series branding ("Question-Based Series #5") and the "let's go" / sign-off exhortations —
  interview-prep framing, no technical content.
- The ASCII architecture and flow diagrams — restated above in prose; the drawings themselves
  are formatting, not additional substance.
- Trailing engagement counters (views/likes/reposts) and the post timestamp — capture artifacts
  of the X render.

## Fidelity check

- **Post count in capture:** 1 (a single long-form article post; `postCount: 1` in the JSON).
- **Article outline as authored:**
  1. Intro (1M req/s framing)
  2. Functional requirements
  3. Layer 4 vs Layer 7
  4. The single entry point — VIP and DNS
  5. The five load balancing algorithms (round robin; weighted round robin; IP hashing;
     consistent hashing; least connections)
  6. Health checks — active and passive
  7. SSL termination
  8. Sticky sessions via Redis
  9. Config system — Zookeeper
  10. The data layer
  11. The full architecture (diagram)
  12. Non-functional requirements (scalability, latency, availability)
  13. Sign-off
- **Pattern → section citations:**
  - L4 vs L7 routing split → section 3 ("Layer 4 vs Layer 7")
  - Virtual IP as the single entry point → section 4 (VIP and DNS)
  - Round robin → section 5, algorithm 1
  - Weighted round robin → section 5, algorithm 2
  - IP hashing → section 5, algorithm 3
  - Consistent hashing → section 5, algorithm 4
  - Least connections → section 5, algorithm 5
  - Dual health checking → section 6 (health checks)
  - SSL termination at the edge → section 7
  - Shared session affinity via Redis → section 8 (sticky sessions)
  - Watch-based dynamic config → section 9 (Zookeeper)
  - Infrastructure-shaped data layer → section 10 (the data layer)
  - Horizontal balancer tier + graceful degradation → section 12 (non-functional requirements),
    with the pool split (API/image/payment) also shown in section 11's diagram
