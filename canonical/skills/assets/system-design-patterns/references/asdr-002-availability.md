---
source: https://algomaster.io/learn/system-design/availability
author: algomaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Availability: engineering uptime through redundancy math

## What it teaches

Availability is the fraction of time a system is reachable and working, computed
as uptime over total time, and conventionally graded in "nines" — where each
extra nine shrinks the annual downtime allowance by roughly an order of
magnitude (about 8.8 hours/year at three nines, ~53 minutes at four, ~5 minutes
at five). The chapter separates availability from reliability: a service can
answer every request (available) yet answer some of them wrongly (unreliable).

Its most transferable insight is composition math. Dependencies chained in
series multiply their availabilities, so every added mandatory hop drags the
whole below its weakest link — three 99.9% components in series yield roughly
99.7%. Redundant components in parallel multiply their failure probabilities
instead, so two 99.9% nodes side by side reach about six nines. Architecture is
therefore largely the art of converting series dependencies into parallel ones.

It catalogs the failure taxonomy you must design against: hardware wears out on
statistically predictable schedules (a fleet of ten thousand servers sees
hundreds of failures a year, so component death is routine, not exceptional);
software fails via bugs, leaks, deadlocks, and cascades; networks fail
intermittently (loss, latency spikes, partitions, DNS); and humans cause a large
share of outages through config typos, bad deploys, accidental deletions, and
capacity misjudgment — which is the argument for automation and guardrails.

Redundancy topologies get detailed treatment. Active-passive keeps a standby
(cold/warm/hot, trading cost for failover speed from minutes down to seconds)
and suits single-leader systems, but the failover path is a risk: an untested
standby and split-brain scenarios lurk. Active-active has every node serving
real traffic, so "failover" is just the balancer dropping a dead node — but it
demands statelessness or shared state and cross-node consistency handling.
Geographically, availability zones are the default isolation unit (independent
power/cooling/network at 1-2ms cost), regions guard against area-wide disasters
at 50-100ms+ replication cost, and multi-cloud hedges provider outages.
Crucially, redundancy must exist at every layer — a redundant app fleet over a
lone database has not solved anything, and the load balancer itself needs a
redundant twin (managed cloud LBs, or a floating virtual IP between two
proxies on-prem).

Four recurring patterns close it out: health-checked load balancing with
automatic ejection of dead backends; database replication with managed
failover, choosing sync (zero loss, added write latency), async (fast, lossy on
failover), or semi-sync (one confirmed replica) per role; queue-based load
leveling to survive burst traffic like flash sales; and circuit breakers
(closed → open on failure threshold → half-open probe → close on success) to
stop cascades by failing fast.

## Key patterns & decisions

- Nines budgeting: pick an availability target from the downtime table and let it drive investment, rather than chasing maximal nines reflexively.
- Series-vs-parallel composition math: every mandatory in-line dependency multiplies risk down; every true redundant peer multiplies risk away — restructure chains into parallel paths.
- Failure-mode taxonomy as a design checklist: hardware, software, network, and human error each need distinct defenses, with human error deserving automation and reversibility guardrails.
- Active-passive standby tiering: choose cold/warm/hot standby by how many minutes or seconds of failover the business tolerates versus the cost of idle capacity.
- Active-active with health-check ejection: eliminate the failover event entirely by having all nodes live, at the cost of stateless design or shared state.
- Multi-AZ as the default isolation posture: AZs give real fault isolation at negligible latency; escalate to multi-region only for disaster-recovery or global-latency requirements, usually with async replication and an accepted loss window.
- Layer-complete redundancy including the balancer: audit every tier (entry, app, data) for a lonely component; redundancy that skips a layer is theater.
- Replication-mode selection per role: synchronous to the failover target, asynchronous to read replicas and analytics.
- Queue-based load leveling: interpose a buffer so spikes accumulate as backlog instead of crushing the datastore.
- Circuit breaker state machine: trip open past a failure threshold, reject instantly, probe with limited traffic after a timeout, and re-close only on success.

## When to apply / trade-offs

Use the composition math at design-review time: it exposes why microservice
chains quietly erode availability and why a single unreplicated dependency
caps the whole product. Choose active-passive when a single writer simplifies
correctness; choose active-active when failover delay is unacceptable and the
service is (or can become) stateless. Match geographic scope to threat model —
multi-region costs latency, money, and consistency complexity, so most
applications should stop at multi-AZ. Every increment of redundancy costs real
money; size it to the business impact of downtime. The closing framing is
worth stealing verbatim as a review question in spirit: for each component,
determine what breaks when it dies, who notices, and how fast recovery happens.

## Fidelity check

1. Claim: parallel redundancy turns two three-nines nodes into roughly six nines. Support: the capture computes both nodes failing simultaneously at 0.1% × 0.1% = 0.0001%, i.e. 99.9999% combined availability.
2. Claim: human mistakes account for a major fraction of outages, motivating guardrails. Support: the failure-modes section attributes a large share of production incidents to config errors, bad deployments, accidental deletions, and capacity misplanning, and argues mature systems make such mistakes preventable or quickly reversible.
3. Claim: standby readiness comes in three cost/speed tiers. Support: the capture's standby table spans cold (powered off, minutes to recover, cheapest) through warm (running but out of rotation, seconds-to-minutes) to hot (synchronized and serving-ready in seconds, priciest).
4. Claim: the load balancer must itself be made redundant. Support: the article flags the LB as a single point of failure and prescribes managed cloud balancers or paired proxy instances sharing a floating virtual IP.
