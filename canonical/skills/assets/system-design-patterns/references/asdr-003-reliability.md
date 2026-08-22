---
source: https://algomaster.io/learn/system-design/reliability
author: algomaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Reliability: correctness over time, not just uptime

## What it teaches

Reliability is the probability that a system does the *right* thing,
continuously, under its stated operating conditions. The chapter's central
move is disentangling four properties that engineers routinely conflate:
availability (did it respond at all), reliability (was the response correct),
fault tolerance (does it keep operating with a component down), and durability
(does data survive failures). These are independent axes — a payment service
that double-charges is available yet unreliable; a database that stays up
through failover but drops in-flight writes is fault-tolerant yet not durable.
Optimizing one can silently damage another: aggressive caching for uptime can
serve stale, i.e. wrong, answers. Users forgive occasional downtime more
readily than wrong answers, which is why correctness deserves first-class
measurement.

On metrics: MTBF (operating time divided by failure count) captures failure
frequency and enables fleet-level forecasting — e.g. a hundred servers each
averaging a couple thousand hours between failures implies roughly one dead
server daily. MTTR (total downtime over failure count) captures recovery
speed, spanning detection, diagnosis, repair, and verification; the chapter
argues that shrinking MTTR usually pays off more than chasing ever-rarer
failures. Error rate targets vary by criticality (from under one-in-ten-
thousand for critical paths to one-in-a-hundred for tolerant ones). The
under-appreciated fourth metric is data correctness: the share of *successful*
responses that carry right answers — a system can post great uptime and error
rates while quietly returning wrong data.

Failure sources: hardware wears out on statistical schedules; software bugs
are systematic rather than random (every request on the bad path fails
identically, and the worst bugs corrupt silently instead of crashing);
configuration mistakes can be catastrophic (the 2017 S3 incident began with a
removal command that took out far more capacity than intended); humans err
under pressure; and overload cascades turn slowdowns into outages when queues
back up, timeouts fire, and retries amplify load.

Defensive techniques: redundant fleets behind balancers; data replication
across nodes/locations; graceful degradation expressed as explicit service
tiers (an e-commerce site stepping down from full personalization to generic
recommendations to bare browse-and-checkout to an emergency cached mode);
circuit breakers (count failures while closed, trip open past a threshold to
reject instantly, half-open to probe recovery); and idempotency — clients
attach a unique key to mutating requests so the server can detect a retry and
replay the stored outcome instead of re-executing, which is why payment
processors mandate idempotency keys for money movement.

## Key patterns & decisions

- Four-axis quality model: score availability, reliability (correctness), fault tolerance, and durability separately; a design review should name which axis each mechanism serves and which it risks.
- MTTR-over-MTBF prioritization: invest in fast detection/diagnosis/recovery rather than trying to prevent every failure.
- Data-correctness as a tracked metric: measure wrong-but-successful responses, not just HTTP errors — silent wrongness is the costliest failure class.
- Systematic-vs-random failure distinction: hardware fails randomly and independently; software bugs fail deterministically on every hit of the path, so redundancy alone cannot mask them.
- Tiered graceful degradation: pre-define full / partial / core-only / emergency service levels so the system sheds optional features instead of collapsing.
- Circuit breaker with half-open probing: fail fast against a sick dependency and re-admit traffic only after successful test requests.
- Idempotency keys for unsafe retries: make ambiguous network outcomes safe to retry by deduplicating on a client-supplied key, mandatory for financial operations.
- Retry-amplification awareness: treat overload cascades (queues, timeouts, multiplying retries) as a first-class failure source, not a corner case.

## When to apply / trade-offs

Apply the four-axis model whenever someone reports "the system is reliable"
with only an uptime number in hand. Prefer MTTR investment when failures are
inevitable at your scale. Design degradation tiers up front for user-facing
products, since improvising them mid-incident fails. The main trade-offs: a
cache tuned for availability risks staleness (a reliability hit); circuit
breakers deliberately reject some recoverable requests to protect the whole;
idempotency requires server-side key storage and a discipline nobody notices
until a duplicate charge appears. The reviewer's question the chapter closes
on: for each dependency, decide what the user experiences if it returns wrong
data, slow data, or nothing — and whether recovery is automatic.

## Fidelity check

1. Claim: the chapter treats correctness of successful responses as a distinct, often-missed metric. Support: it describes a system with 99.99% availability and 0.01% error rate that still has a reliability problem because 1% of its successful responses carry wrong data.
2. Claim: configuration errors can be catastrophic at scale. Support: it cites the 2017 AWS S3 outage, triggered by a server-removal command that unintentionally removed a much larger set of servers than intended.
3. Claim: idempotency keys are how payment providers make retries safe. Support: the capture explains that a stored key lets the server recognize a repeated request and return the saved result without re-executing, and notes that Stripe and PayPal require such keys for money-moving calls.
4. Claim: software bugs differ from hardware faults by being systematic. Support: the failure-sources section contrasts random, independent hardware failures with bugs that break every request traversing the affected code path in the same way.
