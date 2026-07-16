# Resilience Engineering

**A distributed system is a set of failure modes that occasionally computes something. Design for the
failure modes, then go prove they're handled.**

How the **service or system you are building** stays correct and available when its dependencies are
slow, partitioned, overloaded, or down — and how you *verify* that resilience instead of assuming it.
Three disciplines: design for failure (stability patterns), keep distributed decisions correct under
clock skew (bounded time), and inject real failure to find the weaknesses first (chaos engineering).

This is **distinct** from `.claude/rules/agent-resilience.md`, which is about the *coding agent's own
machinery* surviving a tool error or a flaky network. That rule borrows the same vocabulary
(circuit-breaker, fallback, graceful degradation) for the agent's run; **this** rule applies those
patterns to the **product's** services. Same physics, different subject.

## When this rule applies (conditional)

Apply it when the change adds or touches a **networked dependency under load** — a service that calls
another service, a database, a cache, a queue, or a third-party API on a hot path; anything with an
SLO (`.claude/rules/devops-observability.md`); or any decision that depends on ordering events across
more than one machine. **Skip (note why in `CONTINUITY.md`)** for a pure local computation, a
single-process script, or a change with no concurrency-sensitive or cross-node surface.

---

## 1. Stability patterns — design the service to survive its dependencies

A call to a dependency *will* eventually be slow or fail. Without containment, one slow dependency
exhausts your threads/connections, and the failure propagates back up the call graph until the whole
system is down — a **cascading failure**. The patterns below stop the spread. Apply them at every
**remote** call boundary (in-process calls don't need them).

| Pattern | Failure it contains | The discipline |
|---------|--------------------|----------------|
| **Timeout** | A dependency that hangs forever | Every remote call has a finite, explicit deadline. "No timeout" is the most common production outage. Propagate a **deadline/budget** down the call chain so the total stays bounded. |
| **Retry with budget + jitter** | A *transient* blip | Retry only **idempotent** operations, with capped attempts, exponential backoff, and **randomized jitter** (synchronized retries are a self-inflicted DDoS). Cap retries as a **fraction of traffic** (a retry budget), not per-call — so a broad outage can't multiply load. |
| **Circuit breaker** | A dependency that is *down*, not blipping | After a failure threshold, **open** the circuit and fail fast for a cooldown instead of hammering a dead dependency; **half-open** with a trial request before closing. Turns a 30s timeout pile-up into an instant, cheap rejection. |
| **Bulkhead / isolation** | One dependency starving all capacity | Give each dependency (or tenant, or workload class) its **own** pool of threads/connections/permits, so saturating one can't sink the rest — like watertight compartments in a ship. |
| **Backpressure & adaptive concurrency** | More load arriving than you can serve | Bound in-flight work and **shed or queue** the excess rather than accepting everything and collapsing. Prefer an **adaptive** limit over a hand-tuned constant (below). |
| **Load shedding** | Saturation despite limits | When over budget, reject *early and cheaply* (fast 429/503), and **prioritize** — drop low-value/optional traffic first so critical paths keep working. |
| **Graceful degradation / fallback** | A non-critical dependency is unavailable | Serve a sensible default, a cached/stale value, or reduced functionality instead of a hard error — and make the degradation **observable** (it is not "fine"). |

### Adaptive concurrency limiting (don't hand-tune a magic number)

A fixed "max N concurrent" limit is wrong the moment latency changes: too low wastes capacity, too high
lets a queue build until latency explodes. Borrow from **TCP congestion control** and **Little's Law**
(`concurrency ≈ throughput × latency`): measure round-trip latency continuously and **search for the
limit where queueing begins**.

- **Detect the inflection, don't guess it.** Track a baseline (best-observed) latency and the current
  latency; when current latency rises above baseline by a gradient, you are queueing — **shrink** the
  limit. When latency is near baseline, **grow** it. (This is the delay-based / "Vegas"/"Gradient"
  family — the same idea TCP uses to find link capacity without being told.)
- **Place the limit where the queue would form** — at the server (reject to protect the dependency from
  overload and retry storms) and/or at the client (apply backpressure so callers slow down instead of
  piling on).
- **Reserve a floor for critical traffic.** Partition the limit by priority/tenant so a flood of
  low-priority work can't starve SLA-bearing requests.

> Stack-agnostic adaptation of adaptive concurrency limiting (TCP-congestion-control + Little's Law to
> find the limit from latency, server- and client-side, with priority partitioning) from the Apache-2.0
> [`Netflix/concurrency-limits`](https://github.com/Netflix/concurrency-limits). Re-derived in prose;
> not vendored — the algorithm maps onto any language's concurrency primitive (semaphore, pool, worker
> count).

### Partition behavior: choose consistency or availability, per operation (CAP/PACELC)

When the network **partitions**, a replicated store cannot be both consistent and available for a
write — it must either **reject** the operation (stay consistent) or **accept** it and risk divergence
(stay available). This is not one system-wide switch: decide **per operation** by its blast radius.
"Add to cart" can stay available and reconcile later; "charge the card" or "sell the last unit of
stock" must reject rather than double-spend. And the trade-off does not vanish when the network is
healthy — **PACELC**'s *else* clause: absent a partition, you still trade **latency against
consistency**, because stronger consistency costs coordination round-trips. Set that knob per
operation too (a stale read is fine for a dashboard, not for an authorization check). Don't take a
datastore's advertised guarantee on faith — assert the one you depend on with fault injection (§3),
the way partition testing repeatedly surfaces consistency violations the vendor didn't expect.

> Per the CAP / PACELC framing (Eric Brewer; Daniel Abadi) and *Designing Data-Intensive Applications*
> (Martin Kleppmann); "verify, don't trust the guarantee" follows Kyle Kingsbury's Jepsen partition
> testing (jepsen.io). Applied in prose to the per-operation choice, independent of any one datastore.

### Fallbacks and shedding — the sharp edges

Two of the patterns in the table bite back if applied naively:

- **A fallback can amplify the outage it's meant to survive.** If the fallback path itself calls a
  dependency (or retries the failing one), it *adds* load exactly when the system is already failing —
  turning a partial outage into a total one. The safe fallback returns a **static or cached** value and
  introduces **no new dependency at failure time** (*static stability*: pre-provision the answer so the
  degraded path does less work, not more). And always make the fallback **observable** — a silently
  successful fallback masks a real dependency failure.
- **Under overload, drop work that has already missed its deadline.** A request whose deadline has
  passed is worthless to process — its caller has given up (and likely retried), so serving it burns
  capacity for no one. Check the deadline **at dequeue**, not just at accept, and shed the expired work.
  When saturated, prefer serving the **newest** requests first (LIFO): it keeps *some* requests fast
  instead of making *all* of them uniformly slow and stale.

> Per the AWS Builders Library ("Avoiding fallback in distributed systems"; static stability),
> aws.amazon.com/builders-library, and the CoDel / Google SRE intuition on deadline-aware, LIFO-under-
> overload queueing. Applied in prose; the discipline is transport- and language-independent.

**Self-check at every remote call:** does it have a timeout and a deadline budget; is its retry
idempotent, jittered, and budgeted; is there a breaker so a *down* dependency fails fast; and is its
resource pool isolated so it can't starve the rest?

---

## 2. Distributed-time correctness — never trust a single clock for ordering

The moment a decision depends on "did A happen before B?" *across machines*, raw wall-clock timestamps
become a correctness bug. Clocks drift; even with NTP/PTP the synchronization error is bounded but
**non-zero**. Comparing two nodes' timestamps directly can order events backwards.

- **Treat "now" as an interval, not a point.** A correct clock reports `[earliest, latest]` — the true
  time is somewhere inside a window whose width is the **clock error bound** (local offset + drift /
  root dispersion + a share of network delay). A point timestamp silently throws this uncertainty away.
- **Wait out the uncertainty when ordering matters (commit-wait).** To guarantee event B is seen as
  *after* event A across nodes, ensure B's `earliest` exceeds A's `latest` — if needed, **wait** for the
  uncertainty window to pass before committing. This is how globally-consistent ordering is achieved
  without a single coordinator (the TrueTime / ClockBound pattern).
- **Prefer logical ordering where you don't need wall-clock meaning.** For pure causality (not "what
  human time"), **logical/Lamport or vector clocks** order events with no physical-clock dependency at
  all — reach for them first; use bounded physical time only when real-world timestamps must be
  comparable across nodes.

> Stack-agnostic adaptation of bounded-uncertainty time (timestamps as `[earliest, latest]` intervals +
> commit-wait for cross-node ordering) from the MIT/Apache-2.0
> [`aws/clock-bound`](https://github.com/aws/clock-bound) and Google's TrueTime. Re-derived in prose;
> not vendored — the discipline applies wherever distributed nodes order events.

---

## 3. Chaos engineering — verify resilience by injecting failure

Stability patterns and clock discipline are *hypotheses* until something breaks them in anger. **Chaos
engineering** is the discipline of deliberately injecting real-world failure to find the weaknesses
*before* an incident does — empirical verification of the resilience designed in §1–2.

- **Start from a steady-state hypothesis.** Define normal as a **measurable** output (throughput, p99
  latency, error rate, a business metric), then hypothesize it *stays within bounds* during a failure.
  An experiment that doesn't predict a steady-state outcome is just breaking things.
- **Vary real-world events.** Inject the failures that actually happen: instance/process death, a
  dependency returning errors or extra latency, a network partition or packet loss, a full disk, clock
  skew, a resource exhausted. Prioritize by likelihood × impact.
- **Minimize the blast radius, then grow it.** Begin in staging or on a tiny fraction of production
  traffic with a **tested, fast abort** (automatically halt and roll back the instant the steady-state
  metric breaches). Expand scope only as confidence builds. Chaos without a kill switch is an outage.
- **Prefer production, but earn it.** Real weaknesses live in prod (config, scale, real traffic mix);
  run there once experiments are safe and aborts are proven — never as the first step.
- **Automate and make it continuous.** A one-off "game day" finds today's weakness; **automated,
  recurring** experiments catch the regression a deploy introduces next month. Each confirmed weakness
  becomes a fix *and* a permanent experiment (the resilience analogue of a regression test).

A chaos finding is a real defect: classify it by `.claude/rules/quality-gates.md` severity and route the
fix back through the dev lane, the same as any bug.

> Stack-agnostic adaptation of chaos engineering (steady-state hypothesis, vary real-world events,
> minimize blast radius with an automated abort, prefer production, run continuously) from the Apache-2.0
> [`Netflix/chaosmonkey`](https://github.com/Netflix/chaosmonkey) and the Principles of Chaos. Re-derived
> in prose; not vendored — the discipline is independent of any one fault-injection tool.

---

## Relationship to other rules

- **`.claude/rules/agent-resilience.md`** — the same patterns applied to the *coding agent's* own run
  (the agent surviving a tool/network failure), not the product's services. Read both; don't conflate.
- **`.claude/rules/devops-observability.md`** — resilience is unmeasurable without SLOs, burn-rate
  alerting, and the failure-domain progressive-rollout discipline; chaos experiments assert against the
  SLOs defined there.
- **`.claude/rules/quality-gates.md`** — a chaos finding or an unhandled cascading-failure path is a
  finding classified and gated like any other.
- **`.claude/rules/testing.md`** — deterministic simulation testing injects faults *in a reproducible
  simulation*; chaos engineering injects them *in a real environment*. Complementary, not redundant.

**This rule is working if** every remote call on a hot path has a timeout, a budgeted retry, and a
breaker; one slow dependency can't take down the whole service; cross-node ordering never rests on a raw
timestamp comparison; and the system's resilience has been *demonstrated* by injected failure, not just
asserted in a design doc.
