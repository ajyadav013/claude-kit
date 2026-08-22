---
source: https://blog.flipkart.tech/mysql-high-availability-5f71838f19e1
author: Flipkart
license-note: ideas absorbed in own words; no text or code reproduced
---

# Flipkart Altair: automated MySQL failover with split-brain fencing built in

## What it teaches
Flipkart's logistics and commerce domains lean on MySQL primary/replica clusters, and
originally every team ran its own — with wildly uneven tuning, security, and operational
skill, a burden that spiked during Big Billion Days sales. The answer was Altair, an
in-house managed-MySQL platform, and this post dissects its high-availability core: how it
detects a dead primary, filters false alarms, promotes a replica, repoints clients, and —
the hard part — guarantees the old primary can never quietly keep accepting writes.

## Key patterns & decisions
- Centralize database operations into a platform team: a managed service removes per-team
  variance in HA quality and frees product engineers from database toil.
- Three-role detection pipeline: a co-located agent daemon samples instance health (process
  state, disk, replication lag) every 10 seconds; a horizontally scalable monitor service
  (fronting Zookeeper, each node owning a subset of clusters) diffs successive health
  reports and flags breaches; a separate orchestrator owns the decision to act.
- Separate "detecting" from "deciding": only the orchestrator triggers recovery, and its
  first job is disproving the alarm, because failover on an async-replication cluster can
  itself cost data and downtime.
- Deep multi-vantage health checks instead of naive ping-retry: naive N-probes-every-t
  either passes intermittent blips through or delays real recoveries; Altair instead
  cross-checks the VM's state, whether a replica can still reach the primary, and whether
  the orchestrator itself can connect — the primary counts as alive if any of those paths
  succeeds.
- Failover as a resumable workflow of discrete tasks: suspend monitoring, let the replica
  drain its relay backlog, flip the primary read-only (planned cases only), stop the old
  primary, promote the replica, update DNS — each step an individually executable unit.
- Fence before you promote: stopping the old primary machine outright is the split-brain
  guardrail; two simultaneously writable primaries fork the dataset and force a painful
  reconciliation (the post points to GitHub's 2018 incident, where tens of seconds of
  partition took over a day to reconcile).
- Degrade to human coordination when fencing is unverifiable: if a network partition makes
  the old primary's state unknowable, the workflow pauses itself, clients are told to stop
  their applications, and only then does promotion continue — an explicit
  consistency-over-availability choice.
- DNS as the failover-transparent discovery layer: clients resolve the primary through a
  DNS name that is rewritten on promotion, so in the common case no application restart is
  needed.
- Enumerate partition cases explicitly: replica-only partitions trigger nothing; monitor
  cut off from the primary while the orchestrator can still reach it is classified a false
  positive; orchestrator cut off can still promote a reachable replica after fencing.

## When to apply / trade-offs
- Fits any org running many async-replicated database clusters where per-team HA is
  inconsistent; the agent/monitor/orchestrator split is reusable beyond MySQL.
- Async replication means failover can lose the tail of unreplicated writes — the tolerance
  for that loss should drive how aggressive detection and promotion are.
- The pause-and-notify path trades write availability (and human effort) for consistency;
  Flipkart itself flags the reliance on application cooperation as a gap it is closing.
- False-positive filtering adds latency to genuine failures; the multi-path liveness check
  is the compromise between trigger-happy and slow.

## Fidelity check
1. Claim: node death is declared after three missed heartbeats. Capture support: the agent
   reports every 10 seconds, and the monitor marks a node unhealthy after missing three
   consecutive updates, i.e. 30 seconds.
2. Claim: some alarms are deliberately discarded. Capture support: when only the monitor is
   partitioned from the primary but the orchestrator can verify the node and MySQL process
   are healthy, the orchestrator classifies the event as a false positive and does nothing.
3. Claim: the system is battle-tested at fleet scale. Capture support: the post states
   Altair has detected and recovered from more than 500 primary failovers and has run
   through multiple Big Billion Days events.
