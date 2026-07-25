---
source: https://www.druva.com/glossary/what-is-a-failover-definition-and-related-faqs
author: Druva
license-note: ideas absorbed in own words; no text or code reproduced
---

# Failover fundamentals: automatic takeover, cluster topologies, and failback

## What it teaches
Failover is the automatic, ideally user-invisible handoff of work from a
failed primary component to a standing-by backup. This glossary-style page
covers the core mechanics (heartbeat-based failure detection between
paired servers), the two dominant high-availability topologies
(active-active vs active-passive), what a failover cluster is, why failover
must itself be failure-proof for disaster recovery to hold, and the
distinction between failing over and failing back. It is vendor content
(Druva DRaaS pitch at the end) but the underlying concepts are standard.

## Key patterns & decisions
- **Heartbeat-based failure detection** — primary and standby servers are
  linked by a pulse channel; the standby stays dormant while the heartbeat
  continues and initiates takeover when the pulse changes, also paging
  operators to restore the primary.
- **Automated-with-manual-approval as a middle mode** — some setups only
  alert a technician and require a human to execute the switch, trading
  recovery speed for control over false-positive failovers.
- **Active-active vs active-passive as the core topology decision** —
  active-active runs identical service on all nodes simultaneously (load
  spread, near-zero switchover outage, but degraded performance if a
  surviving node was already carrying more than half the load);
  active-passive keeps a synchronized idle standby (simpler, cheaper in
  utilization, but with a takeover delay and lower total throughput).
- **Configuration parity across nodes** — in both topologies the nodes must
  be configured identically so clients perceive no change when the backup
  takes over; drift between primary and standby silently breaks failover.
- **The backup path must itself be immune to failure** — a DR story that
  depends on a standby which can fail the same way as the primary is not a
  DR story; redundancy has to extend to the failover machinery.
- **Virtualization decouples failover from hardware** — VM-based failover
  lets the takeover happen independent of specific physical components,
  which is what makes cloud/DRaaS failover practical.
- **Failover testing as a first-class practice** — regularly validate that
  the system can actually absorb the extra load and shift operations to
  backups during an abnormal termination, rather than assuming the
  configuration works; untested failover is a common resilience gap.
- **Failover vs failback lifecycle** — takeover by the secondary is only
  half the operation; failback is the planned return of production to the
  restored primary site, and it needs to be as deliberate as the failover.
- **CA/FT vs HA cluster distinction** — continuous-availability (fault
  tolerant) clusters aim for zero interruption; high-availability clusters
  accept a brief interruption but promise automatic recovery and no data
  loss.

## When to apply / trade-offs
- Choose active-active when switchover downtime must be near zero and the
  budget supports running full capacity on every node; keep each node's
  steady-state load at or below half so a single failure doesn't degrade
  service.
- Choose active-passive when cost matters more than seconds of takeover
  delay; accept that the standby is nearly idle spend and that failover
  time is nonzero.
- Whatever the topology, treat failover drills (game days) as mandatory:
  the page's emphasis on failover testing maps directly to modern chaos/DR
  exercise practice.
- Remember secondary concerns that ride along: redundant internet links
  (network-level failover), unique domain names and load balancing for
  application-server failover, and DNS redirection during site-level
  failover.

## Fidelity check
1. Claim: standby takeover is triggered by heartbeat change. Capture
   support: the page describes heartbeat cables linking servers, the
   secondary resting while the pulse persists, and initiating its own
   instances plus notifying the data center when the pulse changes.
2. Claim: active-active degrades if a node ran hot before the failure.
   Capture support: the text notes each active-active node must be able to
   carry the full load alone, and that performance suffers on failure if
   one node was consistently handling more than half the traffic.
3. Claim: failback is the distinct return leg. Capture support: the page
   defines failback as moving production back to the original site after
   a disaster or maintenance window, i.e., the return from standby to
   fully functional primary, separate from the failover event itself.

## Notes
Weakest capture of the batch in signal-to-noise terms: it is a vendor
glossary page with heavy whitespace and a closing Druva DRaaS marketing
section, but the technical content present is complete and coherent.
