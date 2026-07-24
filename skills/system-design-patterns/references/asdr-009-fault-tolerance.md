---
source: https://www.cockroachlabs.com/blog/what-is-fault-tolerance/
author: Cockroach Labs (Charlie Custer)
license-note: ideas absorbed in own words; no text or code reproduced
---
# Fault tolerance: choosing what your system must survive, and what that costs

## What it teaches
Fault tolerance is the property of a system that keeps working when some component
breaks. The article anchors this with the November 2020 AWS us-east-1 outage, which
took large swaths of well-known services offline and illustrates why a single point
of failure at any layer is a business risk, not just a technical one. The core mental
model: redundancy at every layer (hardware, software instances, power), an explicit
choice between "users never notice" and "users notice but the system stays up," and a
ladder of survival goals that each cost progressively more to reach. It also draws a
useful line between fault tolerance and high availability: a perfectly redundant
system can still miss availability targets if routine maintenance (upgrades, schema
changes) requires planned downtime.

## Key patterns & decisions
- **Redundancy per layer, not just the database**: duplicate hardware, duplicate
  software instances (e.g., container orchestration restarting/replacing failed
  replicas), and backup power each address a different failure class; a system is
  only as tolerant as its weakest layer.
- **Standby replica as the minimal example**: an app wired to a primary plus a
  standby database survives a database failure via failover; an app on a single
  instance simply stops. Degrees of tolerance exist beyond this baseline.
- **Normal functioning vs graceful degradation**: decide up front whether a failure
  must be invisible to users (expensive, for mission-critical paths) or may reduce
  functionality/slow the experience without a full outage (cheaper, acceptable for
  secondary features).
- **Survival-goal ladder**: pick the blast radius you intend to survive — node
  failure → availability-zone failure → region failure → whole-cloud-provider
  failure — and architect (and budget) for exactly that tier, not vaguely for "HA."
- **Fault tolerance ≠ high availability**: HA is measured total uptime; fault
  tolerance is one input to it. Planned downtime for upgrades or schema changes can
  sink availability even in a fault-tolerant design.
- **Cost the outage, not just the redundancy**: weigh the redundancy bill against
  the cost of downtime in revenue, reputation, engineering hours burned on recovery,
  and team morale/retention (outages love holidays).
- **Buy-vs-build for tolerance mechanisms**: mechanisms that automate distribution
  (e.g., an inherently distributed database) can beat manual approaches (hand-rolled
  sharding of a single-primary RDBMS) on total cost even when the sticker price is
  higher, because the labor and complexity of manual approaches dominate.
- **Pair fault tolerance with RTO/RPO**: surviving a fault is one dimension;
  recovery-time and recovery-point objectives govern the damage when a fault
  exceeds what you built to survive.

## When to apply / trade-offs
Apply the survival-goal ladder at architecture time: most systems only need node- or
AZ-level survival; multi-region and multi-cloud add large cost and operational
complexity and should be justified by a concrete outage-cost analysis. Graceful
degradation is the pragmatic default for non-critical features — reserve
"failure is invisible" engineering for payment/identity-grade paths. Remember 100%
fault tolerance is unachievable; the design question is always "survive what,
at what price." The piece is a vendor blog, so its worked cost example naturally
concludes in favor of the vendor's distributed database — the underlying
buy-vs-build reasoning is still sound if you swap in any managed distributed store.

## Fidelity check
1. Claim: the article motivates fault tolerance with a real large-scale cloud outage.
   Support: the capture opens by recalling the Nov 25, 2020 AWS us-east-1 incident
   and lists major consumer services that broke or degraded because of it.
2. Claim: the article defines an ascending ladder of survival goals. Support: the
   capture enumerates, in order of increasing resilience, surviving node failure,
   AZ failure, region failure, and full cloud-provider failure, each tied to where
   you run instances.
3. Claim: the article distinguishes fault tolerance from high availability.
   Support: the capture states a highly fault-tolerant app can still miss HA if it
   must be taken offline regularly for software upgrades or schema changes.
