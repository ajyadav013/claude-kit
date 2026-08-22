---
source: https://blog.algomaster.io/p/load-balancing-algorithms-explained-with-code
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Choosing a load-balancing algorithm: five strategies and when each wins

## What it teaches

A survey of the five most common request-distribution algorithms a load
balancer can run, framed as an engineering decision: each algorithm trades
implementation simplicity against how much live server state it must observe.
The progression moves from stateless rotation (round robin) through
capacity-aware rotation (weighted), to feedback-driven selection (least
connections, least response time), and finally to deterministic affinity
(IP hash). The core lesson is that "which algorithm" is really a question
about your fleet's homogeneity, your workload's variance, and whether clients
need to keep hitting the same backend.

## Key patterns & decisions

- **Round robin as the homogeneous-fleet default** — cycle through the server
  list in order and wrap around; correct only when every backend has roughly
  equal capacity, because the algorithm is blind to load and latency.
- **Weighted round robin for heterogeneous capacity** — assign each backend a
  weight proportional to its horsepower so bigger machines absorb a
  proportionally larger request share; still static, still blind to live load.
- **Least connections for dynamic load feedback** — route each new request to
  whichever backend currently holds the fewest open connections, which
  requires the balancer to track connection open/close events per server.
- **Least response time for latency-sensitive routing** — continuously
  measure per-backend response times and send traffic to the fastest one;
  adapts to changing conditions but depends on accurate latency measurement,
  which is genuinely hard in distributed systems.
- **IP hash for sticky sessions** — hash the client address modulo the server
  count so a given client deterministically lands on the same backend;
  buys session affinity at the cost of skew (hot clients overload one server)
  and brittle remapping when the fleet changes.
- **Static vs. feedback-driven split** — the first two algorithms decide from
  configuration alone; the last three require runtime state (connection
  counts, latency samples, or client identity), which raises operational cost
  in exchange for better adaptation.

## When to apply / trade-offs

- Uniform fleet, uniform requests: plain round robin — anything fancier adds
  state for no benefit.
- Mixed instance sizes: weighted round robin, but revisit weights when the
  fleet changes since they are set by hand, not measured.
- Workloads with long-lived or highly variable connections (websockets,
  streaming, slow queries): least connections, because request count stops
  being a good proxy for load.
- Latency-dominated user experience with uneven backend performance: least
  response time, accepting the measurement infrastructure it demands.
- Stateful applications that store session data on the backend: IP hash, but
  prefer eliminating server-side session state so any algorithm works; naive
  modulo hashing remaps most clients whenever a server joins or leaves
  (the classic motivation for consistent hashing, though this article stops
  short of covering it).
- General caution the article implies: feedback-driven algorithms can only be
  as good as their signals — stale connection counts or noisy latency samples
  produce worse routing than dumb rotation.

## Fidelity check

1. Claim: least connections requires per-server connection bookkeeping,
   including decrementing on close. Support: the capture describes an
   implementation that keeps a per-server active-connection map, bumps the
   count when a request is assigned, and has an explicit release step invoked
   when a connection finishes.
2. Claim: IP hash gives session persistence but degrades under skewed client
   traffic and fleet changes. Support: the capture lists sticky sessions as
   the use case, and names uneven distribution from high-traffic IPs plus the
   need to reconfigure the hash mapping when a server dies as the drawbacks.
3. Claim: weighted round robin distributes requests proportionally to
   assigned weights. Support: the capture's worked example states that with
   weights of five, one, and one, the first server receives five times as
   many requests as either of the other two.
