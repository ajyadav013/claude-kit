---
source: https://algomaster.io/learn/system-design/single-point-of-failure-spof
author: algomaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Single points of failure are dependency problems, not server counts

## What it teaches

A SPOF is anything — component, external dependency, process, or even a
person — whose failure kills a critical user flow. The definition is
deliberately broad: beyond the obvious lone load balancer or database primary,
SPOFs include DNS providers, secrets managers, deployment pipelines, feature
flag services, shared libraries, a mandatory human approval step, or the one
engineer who knows the recovery procedure. The chapter's sharpest idea is the
three-part test: something is a SPOF only when (a) a critical path depends on
it, (b) no working alternative exists when it dies, and (c) the impact is
unacceptable. A dead recommendations service that degrades the homepage is not
a checkout SPOF; conversely, a cache whose failure dumps unabsorbable traffic
onto the database has become a link in a cascading-failure chain even though
the system "survived" the cache outage itself.

Identification is a dependency-tracing exercise, and the chapter contributes a
genuinely useful distinction between two graphs: the *runtime* graph (what
must be up to serve traffic) and the *recovery* graph (what must be up to fix
things after a failure). A service can keep serving while its secrets manager
is down — until it needs a restart. Replicas exist, but failover is a manual
command one person knows. Region failover works in theory, but the DNS switch
is manual and has never been rehearsed. Restore permissions live in an account
nobody on call can access. Recovery-graph SPOFs surface only mid-incident,
which is the worst time.

Shared fate defeats paper redundancy: primary and replica in the same zone,
"redundant" balancers hanging off one DNS record or network path, multi-region
services on a single global control plane, two services on the same overloaded
database, backups stored in the same account/region as the primaries. Two
components are only redundant if their failure modes are sufficiently
independent — and if the survivor has capacity to carry the doubled load,
otherwise the pair is redundant on paper only.

The failure-review drill asks six questions per component: behavior when it is
slow, erroring, returning bad data, unreachable from one zone, recovering with
stale state, or failed-over at reduced capacity. Slowness is singled out as
more dangerous than clean death, because a hung dependency ties up threads,
pools, and retry budgets without tripping health checks. Assumptions must be
validated by controlled failure injection — targeted, hypothesis-driven tests
(kill an instance, block a replica, force a rebalance, then zone kills, DNS
breaks, restore drills, region failover timing) rather than unfocused chaos.

Mitigations span redundancy (active-active vs active-passive, with the warning
that an unexercised standby is unproven), health-checked load balancing (with
readiness-not-liveness checks, connection draining, load shedding, versioned
LB config, and capacity-aware cross-zone routing), replication choices
(sync/async/multi-primary/read-replicas) with the emphatic reminder that
replication is not backup — corruption replicates fast, and a backup is
unproven until restored end-to-end — failure-domain isolation (multi-AZ first,
multi-region only when justified), explicit graceful degradation (labeled
limited-mode beats confident stale answers), and containment via timeouts,
bounded jittered retries, circuit breakers, bulkheads, load shedding, rate
limits, and idempotency keys. Monitoring and runbooks close the loop: an alert
without a responder who knows the procedure is itself an operational SPOF.

Notably, the chapter extends the catalog to AI/ML systems: one shared vector
database, a model gateway without regional failover, a single embedding
service, a policy service every prompt transits, or a quota service that fails
closed — while noting some components *should* fail closed for safety, as an
explicit documented decision rather than an accident.

## Key patterns & decisions

- Three-condition SPOF test: critical-path dependency + no alternative + unacceptable impact; analyze user flows, not server inventory.
- Runtime vs recovery dependency graphs: audit what you need to *repair* the system (deploys, secrets rotation, flag changes, failover commands, restore permissions), not just what serves traffic.
- Shared-fate detection: redundancy is void when peers share a zone, DNS record, network path, control plane, database, queue partition, or backup account.
- Six-question failure review per component: slow, erroring, bad-data, partially unreachable, stale-state recovery, and reduced-capacity failover — with slow dependencies flagged as the stealthiest killer.
- Hypothesis-driven failure injection: chaos tests tied to explicit expectations (named latency and utilization bounds) instead of random fault noise.
- Replication is not backup: replicas propagate corruption; a backup counts only after a full restore rehearsal including permissions.
- Capacity-checked redundancy: N+1 only works if survivors can absorb the redistributed load; routing to a healthy-but-undersized zone helps nothing.
- Explicit SPOF disposition: for each identified SPOF choose remove / mitigate-with-degradation / monitor-and-accept / roadmap-with-trigger, weighted by business impact.
- Deliberate fail-closed choices: safety-critical gates (e.g. an AI policy check) may correctly block on outage — but as a documented decision.
- Operational SPOFs are real: single pipelines, runbooks, cloud accounts, and lone experts fail systems just as hardware does.

## When to apply / trade-offs

Run this analysis on every critical flow (sign-in, checkout, payment, upload,
inference, rollback) at design time and before incident-readiness reviews. The
trade-off framing is refreshingly non-dogmatic: eliminating every SPOF is
neither free nor always right — redundancy buys cost, complexity, consistency
decisions, and new misconfiguration surfaces. Accepting a SPOF in a prototype
or low-stakes internal tool is fine; the sin is an *unknown* SPOF in a
critical path. Investment should track business impact — the checkout database
merits engineering the badge-count cache does not. The closing operational
question generalizes to any component: if it fails right now, what breaks, who
notices, and how does recovery proceed?

## Fidelity check

1. Claim: the chapter distinguishes a runtime dependency graph from a recovery graph. Support: it describes systems that keep serving traffic during an outage yet cannot deploy, rotate credentials, or fail over — e.g. an app that cannot restart because the secrets manager is down, and replicas whose failover is a manual command only one person can run.
2. Claim: slow dependencies are called out as more dangerous than outright failures. Support: the failure-review section notes hard failures trip health checks while a slow dependency silently exhausts threads, connection pools, queues, and retries until the service degrades wholesale.
3. Claim: replication and backup are treated as distinct necessities. Support: the capture warns that replicated deletion or corruption spreads quickly, that backups defend against operator mistakes, bugs, and ransomware, and that a backup's recoverability is unproven until an end-to-end restore has been performed.
4. Claim: the chapter includes AI-specific SPOFs. Support: it lists a single shared vector database cluster, a model gateway lacking regional failover, one queue owning all batch inference, a lone embedding service, and a fail-closed quota/policy service as AI-path single points of failure.
