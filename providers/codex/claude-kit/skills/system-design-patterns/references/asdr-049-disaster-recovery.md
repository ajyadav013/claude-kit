---
source: https://cloud.google.com/learn/what-is-disaster-recovery
author: Google Cloud
license-note: ideas absorbed in own words; no text or code reproduced
---

# Disaster recovery planning: RTO/RPO-driven restoration of IT operations

## What it teaches

A vendor explainer (Google Cloud, so cloud-forward framing throughout) on disaster
recovery as the IT-focused subset of business continuity: the discipline of getting
the systems that support critical business functions running again after a
disruptive event. "Disaster" is defined broadly — cyber attacks (ransomware, DDoS,
malware), infrastructure hazards like power loss, hardware failure, natural events,
and plain human error all qualify. The piece argues DR is no longer optional because
data-privacy regulation increasingly mandates it, and failure has compounding costs:
lost data, lost revenue, fines, and reputational damage.

The planning method it presents is a five-step loop: assess risks and
vulnerabilities; run a business impact analysis quantifying what each disruption
costs in money, reputation, and compliance exposure; write the DR plan itself with
explicit roles, recovery procedures, and communication protocols; implement it with
backup/replication systems and failover mechanisms; then test regularly and update
as the environment changes. Testing is treated as a first-class step, not an
afterthought — an untested plan is presumed broken.

Controls are grouped into three complementary categories: preventive (hardening,
backups, continuous monitoring for misconfiguration and compliance drift so the
disaster never happens), detective (real-time discovery that something has gone
wrong, since fast recovery starts with fast detection), and corrective (rehearsed
procedures that restore data and systems when the time comes). Operationally, DR
means replicating critical data and workloads to one or more secondary locations
that can either serve restores or take over entirely while the primary is rebuilt.

Two metrics anchor every strategy decision. Recovery time objective (RTO) is the
longest tolerable outage per system — some apps can be down an hour, others only
minutes — and recovery point objective (RPO) is the maximum age of data you can
afford to lose, which directly dictates backup frequency. The menu of mechanisms
spans plain offsite backups (data only, no infrastructure — suited to archival and
compliance retention), backup-as-a-service, DRaaS (a third party hosts replicas and
orchestrates failover for you), point-in-time snapshots (fast recovery from
corruption or accidental deletion, with loss bounded by snapshot cadence),
virtualized DR (a full replica environment on offsite VMs for rapid failover), and
physical DR sites (for organizations with strict compliance or physical-control
needs). The 3-2-1 rule appears as the baseline backup posture: three copies of the
data, on two different media types, with one copy offsite. The piece also
distinguishes backup (a data-copy mechanism) from DR (the whole restore-the-business
strategy that backup merely feeds), and notes high-availability features complement
DR by absorbing the small-scale failures that never escalate.

## Key patterns & decisions

- **RTO/RPO as the sizing dials**: define maximum tolerable downtime and maximum
  tolerable data age per system first; every technology choice and backup cadence
  follows from those two numbers.
- **Five-step DR lifecycle**: risk assessment, business impact analysis, plan
  authorship, implementation, and recurring test-and-revise — a loop, not a one-time
  document.
- **Preventive/detective/corrective control triad**: invest across stopping disasters,
  noticing them fast, and rehearsing the recovery, not in one bucket alone.
- **3-2-1 backup rule**: three copies, two media types, one offsite — the minimum
  posture against correlated loss.
- **Backup is not DR**: a data copy is one ingredient; DR is the tested end-to-end
  capability to restore systems and operations.
- **Tiered recovery mechanisms**: match mechanism to need — snapshots for corruption
  rollback, virtual/DRaaS failover for minimal downtime, plain backups for archival,
  physical sites only when compliance demands.
- **DR testing as a standing obligation**: regularly exercise the plan to expose
  weaknesses and keep it aligned with a changing environment.
- **Compliance as a DR driver**: privacy laws and industry standards increasingly
  require documented, tested recovery capability, with fines for gaps.

## When to apply / trade-offs

- Apply the RTO/RPO framing whenever designing backup jobs, replication topologies,
  or failover automation; it converts vague "be resilient" asks into measurable
  requirements and prevents both over- and under-spending.
- The mechanism tiers trade cost against speed: snapshots and backups are cheap but
  lose more and restore slower; hot virtual replicas and DRaaS shrink RTO/RPO at
  ongoing expense; physical secondary sites are the costliest and, per the (self-
  interested) vendor argument, mostly obsoleted by cloud regions.
- Note the source bias: this is marketing content for Google Cloud's backup/DR
  products, so cloud-eliminates-the-DR-site claims deserve skepticism for
  organizations with sovereignty, latency, or regulatory constraints.
- HA and DR are complements, not substitutes — redundancy and automatic failover
  absorb small failures, but only a tested DR plan covers region-scale or malicious
  events.

## Fidelity check

1. *Claim:* the article prescribes a five-step DR process ending in continuous
   testing. *Support:* the capture enumerates risk assessment, business impact
   analysis, DR planning, implementation, and testing-and-maintenance, with the last
   step explicitly requiring regular exercises and plan updates.
2. *Claim:* RTO and RPO are presented as the two metrics that shape a DR strategy.
   *Support:* the capture defines RTO as the maximum acceptable downtime before
   serious business damage and RPO as the maximum age of recoverable data, adding
   that RPO drives backup frequency.
3. *Claim:* the 3-2-1 rule is given as the baseline backup practice.
   *Support:* the capture's FAQ spells out keeping three copies of data on two
   distinct storage media with one copy offsite, to survive hardware failure,
   software corruption, and natural disasters.
