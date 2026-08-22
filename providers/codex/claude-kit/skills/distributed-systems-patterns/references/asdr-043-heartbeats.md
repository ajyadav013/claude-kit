---
source: https://blog.algomaster.io/p/heartbeats-in-distributed-systems
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Heartbeats: periodic liveness signals as the foundation of failure detection

## What it teaches

In any distributed system, components fail — hardware dies, processes crash, links
drop — and the system cannot react to a failure it has not detected. A heartbeat is
the simplest detection primitive: a small message emitted at a fixed cadence
(seconds to minutes, workload-dependent) whose only essential meaning is "this node
is still functioning." A monitor tracks arrivals; when an expected heartbeat window
elapses without a signal, the node is marked failed and the system triggers a
response — rerouting traffic, failing over, restarting the component, or paging a
human. Without this mechanism, fault detection is slow and ad hoc, downtime
stretches, and reliability degrades.

The mechanism has exactly two roles — a sender (the monitored node) and a receiver
(the monitor that maintains alive/failed state) — and two delivery styles: push
(nodes proactively emit signals) and pull (the monitor polls nodes for status).
Despite its simplicity, three tuning knobs carry all the design weight: frequency,
timeout, and payload. The article grounds the pattern in real systems: primary and
replica databases exchange heartbeats to drive failover; Kubernetes nodes heartbeat
to the control plane, which folds liveness into scheduling; Elasticsearch nodes
heartbeat within a gossip network that doubles as membership discovery and
cluster-state sharing.

## Key patterns & decisions

- **Periodic liveness signal + monitor timeout**: declare a node dead only after a
  missed-heartbeat window, never on a single missed message; detection latency is
  bounded by interval × misses tolerated.
- **Frequency/bandwidth trade-off**: shorter intervals detect failures faster but
  consume network and CPU; longer intervals are cheap but slow to notice death — the
  interval is a deliberate engineering choice, not a default.
- **Timeout calibrated to network latency**: too-aggressive timeouts misclassify
  slow-but-alive nodes (false positives); too-lenient timeouts delay recovery.
- **Piggybacked telemetry on heartbeats**: beyond a timestamp/sequence number, the
  payload can carry load, health metrics, or version info, turning liveness pings
  into a lightweight monitoring channel (and feeding load balancers routing signal).
- **Push vs. pull monitoring**: nodes emit to a monitor, or the monitor polls nodes —
  choose per topology and firewall/ownership constraints.
- **Failure detection wired to automated recovery**: a missed-heartbeat verdict
  should trigger a concrete action (traffic redirection, failover, restart, alert),
  not merely a status flip.
- **Split-brain awareness**: a partition can make both sides declare the other dead;
  heartbeats alone cannot resolve this and need higher-level mechanisms (quorum,
  fencing) layered on top.

## When to apply / trade-offs

Apply wherever one component's availability decisions depend on another's health:
replication failover, orchestrator scheduling (Kubernetes node status), cluster
membership (Elasticsearch gossip), and load balancing away from sick instances.

The trade-offs are all in the tuning: heartbeat traffic itself can congest a large
fleet; monitoring consumes resources; and every threshold is a bet on network
behavior — false positives cause needless failovers, false negatives prolong
outages. The pattern's hardest edge case is the network partition, where symmetric
"you're dead" verdicts (split brain) demand quorum or arbitration beyond the
heartbeat layer. For claude-kit-style guidance this maps directly onto resilience
rules: liveness checks are necessary but must be paired with conservative timeout
policy and an explicit partition story.

## Fidelity check

1. Claim: failure is declared after several missed heartbeats within an expected
   window, not one. Capture support: the article's mechanism walkthrough says the
   monitor marks a node unavailable when signals stop arriving within the expected
   timeframe, and earlier notes that missing several expected heartbeats is the
   signal something is wrong.
2. Claim: heartbeat payloads can carry more than liveness. Capture support: the
   payload discussion states heartbeats typically hold a timestamp or sequence
   number but may also include current load, health metrics, or version data, and a
   separate benefit bullet describes load balancers using node heartbeat health for
   task distribution.
3. Claim: Kubernetes and Elasticsearch both build on heartbeats but differently —
   node-to-control-plane vs. peer gossip. Capture support: the real-world examples
   section describes Kubernetes nodes sending regular heartbeats to the control
   plane for availability tracking and scheduling, while Elasticsearch nodes
   exchange heartbeats to form a gossip network used for discovery, cluster-state
   sharing, and failure detection.
