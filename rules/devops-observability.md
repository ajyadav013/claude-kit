# DevOps & Observability Phases

Two delivery-side phases that run **after** the test-coverage merge gate (MR3 VERIFIED) and **before** the PR Raiser, so that pipeline and observability artifacts ship *inside* the same PR as the code. They are owned by dedicated agents and each has its own quality gate.

```
... MR3 (test coverage VERIFIED)
      -> [DevOps]        devops-engineer        -> Gate: Pipeline Green
      -> [Observability] observability-engineer -> Gate: Observability Ready
      -> PR Raiser
```

## When these phases run (conditional)

Run them when the change touches a **deployable or observable surface**:
- a new/changed endpoint, service, container, dependency, env var, port, or migration;
- anything that adds a user-facing critical path worth an SLO or an alert.

**Skip (note in CONTINUITY.md why)** for pure-internal changes with no deployment or observability surface — a refactor behind an unchanged interface, a copy tweak, a test-only change. Fast-track (Mode D) skips both unless infra/observability is the actual subject of the fix.

---

## Phase: DevOps  ·  Agent: `devops-engineer`  ·  Gate: **Pipeline Green**

Owns the infra seam (containerization, orchestration, migrations-at-boot, ports, CORS, env). For a feature, it ensures the change is **buildable and deployable**, not just runnable on the author's machine.

**Pipeline Green passes when:**
- [ ] CI config is valid and includes lint + type-check + unit tests for the changed stack(s) (CI pipeline config files — editing those requires user approval per CLAUDE.md).
- [ ] Container orchestration config resolves; a clean rebuild and restart brings all services up **healthy**.
- [ ] New env vars are in the project's settings/config, orchestration config, `.env.example`, and the README table.
- [ ] Migrations (if applicable) apply cleanly at boot and have a working rollback/downgrade.
- [ ] A short **runbook** entry exists for anything operationally new (how to deploy it, how to roll it back).
- [ ] No secrets committed; ports/CORS changes reflected in README.

Findings classified by `.claude/rules/quality-gates.md` severity; Critical/High/Medium block.

---

## Phase: Observability  ·  Agent: `observability-engineer`  ·  Gate: **Observability Ready**

Ensures the feature is **operable in production**: you can tell when it breaks and why. Builds on the project's existing health endpoints and structured logging.

**Observability Ready passes when:**
- [ ] **SLOs/SLIs** defined for each critical user journey the feature adds (e.g., "p95 endpoint latency < 200ms", "login success rate ≥ 99.5%").
- [ ] **Load verified against the SLO** — for a change to a hot / SLO-bearing backend path, an empirical load run (drive `.claude/skills/load-testing`) was executed against the defined SLO and **met** its p95/p99 latency + error-rate + throughput budgets; record it under `docs/performance/` and link it from the feature SLO doc. *Skip (note why in `CONTINUITY.md`) for changes with no concurrency-sensitive surface.* A budget breach is **High** (`.claude/rules/quality-gates.md`).
- [ ] **Health/readiness** — any new external dependency (database, cache, third-party service) is reflected in the readiness check; liveness stays dependency-free.
- [ ] **Structured logging** — new state changes log via the project's structured logger as JSON key-values, semantic event names, **no secrets/PII**; error paths log at `error`/`exception` level.
- [ ] **Alerts** — alert rules defined for the feature's failure modes (error-rate spike, latency breach, dependency down) with a severity and an owner.
- [ ] **Traceability** — correlation/request id flows through new code paths where the stack supports it.

Findings classified by `.claude/rules/quality-gates.md` severity; Critical/High/Medium block.

### Multi-window burn-rate alerting (alert on the error budget, not raw error rate)

A static "error rate > X%" alert forces a bad trade-off: tight enough to catch a real outage means it
pages on every transient blip; loose enough to be quiet means slow burns go unnoticed until the budget
is gone. The SRE pattern is to alert on **how fast the SLO's error budget is burning**, across
**multiple time windows** at once:

- **Burn rate = (observed error ratio) ÷ (1 − SLO target).** A burn rate of 1 exactly exhausts the
  budget over the SLO window; 14.4 exhausts it in ~2 % of the window.
- **Fast-burn (page):** a high burn rate confirmed over a **short *and* a medium** window (e.g. 14.4×
  over 1h **and** 5m) — catches acute outages fast while the second window suppresses single-spike
  false positives.
- **Slow-burn (ticket, not page):** a lower burn rate over **longer** windows (e.g. 6× over 6h/30m,
  3× over 24h/2h, 1× over 3d/6h) — catches a steady leak that would otherwise quietly drain the budget.
- Require **both** windows of a tier to fire (the long window detects, the short window confirms it's
  still happening) so an alert clears quickly once the issue stops. Tie each tier's severity/owner to
  the "Alerts" gate item above.

> Stack-agnostic adaptation of multi-window, multi-burn-rate SLO alerting (per the Google SRE Workbook)
> from the Apache-2.0
> [`google/prometheus-slo-burn-example`](https://github.com/google/prometheus-slo-burn-example).
> Re-derived in prose; not vendored — the windows/multipliers are a starting point to tune per SLO.

### High-volume logging: rate-limit and defer

Logging on a hot path or in an error burst can become its own incident — the log call dominates CPU, or
a flood of identical lines buries the signal and runs up ingestion cost. Two patterns keep logging cheap
under load:

- **Rate-limit repetitive log statements at the call site** — emit "at most every N seconds" or "1 in
  every N" for a given line, rather than once per iteration, so a tight loop or a sustained error
  doesn't flood. (Aggregate the suppressed count so you still know the true volume.)
- **Defer the cost of expensive log arguments** until logging is *known to be enabled* at that level —
  pass a lazily-evaluated value (a thunk/lambda), not an eagerly-built expensive string, so a disabled
  `debug` log costs nothing. This pairs with the "no secrets/PII" structured-logging gate item above.

> Stack-agnostic adaptation of log rate-limiting (`atMostEvery`) and lazy argument evaluation from the
> Apache-2.0 [`google/flogger`](https://github.com/google/flogger). Re-derived in prose; not vendored —
> the patterns apply to any logging framework.

### Continuous performance-regression gate (A/B, not absolute thresholds)

The Load-vs-SLO gate above is a *one-shot, pre-launch* check against an absolute budget. It won't catch a
**gradual** regression — a change that quietly adds 15 ms per release until the SLO is blown six PRs
later. For a hot / SLO-bearing path, add a **continuous** check that compares *this commit to a baseline*
on every change:

- **A/B the two commits to cancel environmental noise.** A single absolute number ("p95 = 210 ms") is
  dominated by CI-runner variance, thermal throttling, and noisy neighbors — comparing today's run to
  last week's run measures the *environment*, not the *code*. Instead run **control (baseline commit) and
  treatment (the PR's commit) on the same machine, interleaved/concurrently**, and report the **relative
  delta** (latency ratio, throughput delta), which cancels the shared environmental component.
- **Gate on the delta, with a tolerance band.** Fail the check when the treatment is worse than control
  by more than a stated margin (e.g. ">5 % p95 latency"); a band absorbs residual noise so the gate
  isn't flaky. A breach is **High** (`.claude/rules/quality-gates.md`) — same severity as a Load-vs-SLO
  breach — and routes the fix back to the dev lane.
- **Scope it.** Run it for changes to a concurrency-sensitive or SLO-bearing path; *skip (note why in
  `CONTINUITY.md`)* for changes with no performance surface. It complements, not replaces, the one-shot
  Load-vs-SLO gate (absolute budget at launch) and frontend statistical benchmarking
  (`.claude/skills/performance-optimization`).

> Stack-agnostic adaptation of A/B continuous performance-regression detection (concurrent
> control/treatment runs to isolate code from environment; gate on the relative delta) from the
> Apache-2.0 [`facebook/FAI-PEP`](https://github.com/facebook/FAI-PEP). Re-derived in prose; not vendored.

### Failure-domain-aware progressive rollout (contain the blast radius)

A new revision is the most likely cause of the next outage, so **never deploy it everywhere at once**.
Roll it out progressively, and make the rollout *respect the system's failure boundaries* so a bad
revision can only ever take down one of them:

- **One failure domain at a time.** Identify the unit of correlated failure — an availability zone, a
  region, a rack, a data center, a shard, a cell — and **update only one at a time, never several
  simultaneously**. If the new revision is poison, at most one domain is affected and the rest keep
  serving. (This is orthogonal to canary/feature-flags: canary picks *how much* traffic sees the
  change; this picks *which blast-radius boundary* it's confined to.)
- **Accelerate as confidence builds.** Within a domain, update in **exponentially growing batches**
  (e.g. 1 → 2 → 4 …, capped by a max-unavailable bound), with a **readiness/health gate between
  batches** — proceed only once the just-updated units are healthy. Slow where it's risky (the first
  units), fast where it's proven.
- **Roll back in reverse order, newest-first.** On failure, undo the **most-recently-updated units
  first** — they're the ones running the bad revision, so reversing chronologically escapes it fastest
  instead of waiting out the units that were never touched.
- **Pause on the alarm automatically.** Wire the rollout to the SLO signals above (burn-rate alert,
  canary error-rate/latency breach) so a regression **halts progression** without a human in the loop;
  a breach is **High** (`.claude/rules/quality-gates.md`) and routes the fix back to the dev lane.
- **Scope it.** Worth the machinery for a multi-domain / SLO-bearing service; *skip (note why in
  `CONTINUITY.md`)* for a single-instance or non-critical surface.

> Stack-agnostic adaptation of zone-aware progressive rollout (one failure domain at a time, exponential
> batches with readiness gates, reverse-order rollback, pause-on-alarm) from the Apache-2.0
> [`aws/zone-aware-controllers-for-k8s`](https://github.com/aws/zone-aware-controllers-for-k8s).
> Re-derived in prose; not vendored — the discipline applies to zones/regions/racks/cells/shards on any
> platform, not just Kubernetes.

---

## Notes

- Both agents follow the **RARV cycle** (`.claude/rules/rarv-cycle.md`) and update `CONTINUITY.md` at handoff.
- Neither agent writes application business logic — they own infra and operability only. Logic gaps go back to the relevant dev lane.
- Editing CI pipeline config, package manifests, or other project-wide files still requires explicit user approval (CLAUDE.md §"Files that require user approval").
