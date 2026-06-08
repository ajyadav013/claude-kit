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
- [ ] **Health/readiness** — any new external dependency (database, cache, third-party service) is reflected in the readiness check; liveness stays dependency-free.
- [ ] **Structured logging** — new state changes log via the project's structured logger as JSON key-values, semantic event names, **no secrets/PII**; error paths log at `error`/`exception` level.
- [ ] **Alerts** — alert rules defined for the feature's failure modes (error-rate spike, latency breach, dependency down) with a severity and an owner.
- [ ] **Traceability** — correlation/request id flows through new code paths where the stack supports it.

Findings classified by `.claude/rules/quality-gates.md` severity; Critical/High/Medium block.

---

## Notes

- Both agents follow the **RARV cycle** (`.claude/rules/rarv-cycle.md`) and update `CONTINUITY.md` at handoff.
- Neither agent writes application business logic — they own infra and operability only. Logic gaps go back to the relevant dev lane.
- Editing CI pipeline config, package manifests, or other project-wide files still requires explicit user approval (CLAUDE.md §"Files that require user approval").
