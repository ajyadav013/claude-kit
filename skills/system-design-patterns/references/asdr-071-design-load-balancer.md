---
source: https://algomaster.io/learn/system-design-interviews/design-load-balancer
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Designing a Load Balancer: data-plane speed, control-plane management, and the SPOF paradox

## What it teaches

How to design the traffic-distribution layer itself rather than merely use one. The
chapter frames a load balancer as two systems glued together: a hot data plane that
must forward millions of requests per second entirely from memory, and a cooler
control plane (registration APIs, health checking, configuration) that can afford
slower, persistent operations. It then works through the central irony of the
component: a device you introduce to remove single points of failure becomes one
itself, so the design must make the balancer redundant too (VRRP failover,
active-active clusters, anycast). Along the way it surveys the algorithm menu
(round robin through consistent hashing), health-check tuning, session stickiness
options, the L4-vs-L7 split, and TLS termination trade-offs.

## Key patterns & decisions

- **Data-plane / control-plane separation** — request forwarding never touches disk
  or a remote store; config and health state are pushed into node memory from a
  slower management layer backed by etcd/Consul/Postgres.
- **Estimation drives the shape** — at ~1M req/s the binding constraint is network
  bandwidth (tens of GB/s, beyond one NIC), not memory (~500 bytes of per-connection
  state means connection tracking is cheap), which forces a multi-node design from
  day one.
- **Threshold-based health state machine** — mark a backend down only after 2-3
  consecutive probe failures and up only after 2-3 consecutive successes, so a single
  network blip does not cause flapping; typical cadence is a 5s interval with a 2-3s
  timeout.
- **Connection draining on removal/failure** — stop new traffic instantly but let
  in-flight requests finish (bounded by a timeout) before fully evicting a backend.
- **Weighted least-connections as the sensible default** — combines static capacity
  weights with live connection counts, adapting to slow backends and variable
  request costs; plain round robin is only safe for homogeneous servers with uniform
  work.
- **Consistent hashing with virtual nodes** — reserve it for pools that scale up and
  down frequently or for cache tiers, because it limits remapping to the departed
  node's share instead of reshuffling nearly everything the way `hash % n` does.
- **Sticky-session hierarchy** — best is an externalized session store in the app
  (no stickiness needed at all); next is LB-injected cookies at L7; IP hashing is a
  last resort because NAT funnels whole offices onto one backend.
- **HA pattern choice** — active-passive with a virtual IP claimed via VRRP/ARP is
  simple but idles half the fleet and fails over in 1-3s; active-active (fronted by
  DNS, an upstream L4 tier, or anycast/BGP) uses all capacity and degrades instead
  of failing, at the cost of shared session state (e.g., Redis).
- **TLS termination at the edge** — centralizes certificate management, offloads
  crypto CPU from backends, and enables content-based routing; when compliance
  demands encrypted hops, choose re-encryption (double crypto cost) or SNI-based
  passthrough (lose L7 routing).
- **Plan for dropped connections during failover** — live TCP state cannot
  practically migrate between nodes, so design for stateless failover: fast VIP/BGP
  convergence, client retry logic, external session storage.

## When to apply / trade-offs

Apply this decomposition whenever building or evaluating any traffic-routing tier:
API gateways, service-mesh ingress, or an internal proxy layer. The L4/L7 decision
is the first fork: L4 for raw speed and non-HTTP protocols, L7 whenever routing
needs URL/host/cookie awareness (roughly an order of magnitude throughput penalty
for the parsing). Active-passive suits small deployments that value simplicity;
anything at serious scale should go active-active and accept the shared-state
complexity. The recurring trade-off is adaptiveness versus statefulness: smarter
algorithms (least-connections variants) need per-node counters, while stateless
ones (hashing) are trivially distributed but blind to real load.

## Fidelity check

1. *Claim:* bandwidth, not memory, is the bottleneck at the stated scale.
   *Support:* the capture's estimation section computes roughly 250 MB of connection
   state for half a million concurrent connections versus ~12 GB/s of traffic, and
   concludes a single 10 Gbps NIC is insufficient while memory is a non-issue.
2. *Claim:* consistent hashing exists to shrink remapping churn.
   *Support:* the capture contrasts modulo hashing (going from 3 to 2 backends
   remaps about two-thirds of clients) with the ring approach (only the removed
   node's arc, about one-third, moves), and adds 100-200 virtual nodes per backend
   to even out arc sizes.
3. *Claim:* failover cannot preserve open TCP connections, so the guidance is to
   design around that. *Support:* the follow-ups section states there is no
   practical way to hand a live connection between machines, and recommends fast
   failover plus client retries and an external session store to soften the impact.
