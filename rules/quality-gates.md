# Quality Gates, Severity & Blind Review

This rule adds three things on top of the existing pipeline in `mandatory-workflow.md`:

1. a single **severity model** every reviewer and tester classifies findings against,
2. **gate semantics** (PASS / FAIL / retry / escalate) shared by all gates, and
3. a **blind review + Devil's Advocate** protocol that prevents AI reviewers from rubber-stamping each other.

It does not replace the pipeline gates already defined in `mandatory-workflow.md` — it standardizes *how* those gates decide PASS vs FAIL.

---

## 1. Severity Model

Every finding from a reviewer, tester, security agent, or merge reviewer is classified into exactly one severity. Severity drives whether a gate blocks.

| Severity | Definition | Gate action |
|----------|-----------|-------------|
| **Critical** | Security hole, data loss, authorization bypass, crash, build broken | BLOCK — fix immediately, re-run the lane |
| **High** | Broken functionality, failing acceptance criterion, major bug | BLOCK — fix before the gate passes |
| **Medium** | Minor bug, code smell, perf issue, missing edge-case handling | BLOCK — fix before delivery (PR) |
| **Low** | Style nit, minor naming, non-blocking doc gap | Note as TODO — does not block |
| **Cosmetic** | Formatting, wording preference | Informational — no action required |

**Blocking rule:** a gate is **PASS** only when zero Critical, zero High, and zero Medium findings remain open. Low/Cosmetic may pass with notes. This matches the existing reviewer rule "do not approve with unresolved critical or high-severity issues" and tightens Medium to block before PR.

**Auto-Critical findings** (never downgrade these):
- A hardcoded secret, password, API key, or token in code or configuration.
- Missing authentication or authorization checks on a protected endpoint/resource.
- Missing tenant/organization scoping on a multi-tenant query (authorization bypass).
- Blocking I/O on an async/event-loop execution path (deadlock risk).
- Error suppression that hides failures (blanket exception catching, type-cast to silence errors, linter disable without justification).
- Broken build (lint errors, type errors, compilation failures, import errors).

---

## 2. Gate Semantics

Every gate is binary: **PASS** or **FAIL**.

```
Phase completes -> Gate
  PASS  -> advance to next phase
  FAIL  -> fix highest-severity findings first
        -> log the miss to CONTINUITY.md (and agent-memory if durable)
        -> retry the gate
  retries exhausted -> escalate to human with unresolved findings
```

**Retry budgets** (already in `mandatory-workflow.md`; restated for one place):
- Design review: 3 · Senior dev: 3 · Tech architect: 3 · EM: 3
- Code review: 5 · Merge reviewer: 2 · Defect loop: 2 cycles

When a gate FAILs, the agent records the miss in `CONTINUITY.md` under **Mistakes & Learnings** so the same defect is not reintroduced on retry.

---

## 3. Blind Review + Devil's Advocate

Applies wherever **multiple reviewers assess the same artifact in parallel** — primarily:
- the **test-coverage merge gate** (multiple independent test lanes feeding the merge reviewer), and
- any **multi-reviewer review phase** the Orchestrator runs in parallel.

### Blind review
1. Reviewers assess **independently** — each gets the artifact + spec + rules, none sees another's findings until all have reported.
2. Each returns a structured verdict: `PASS | FAIL` + findings classified by the severity model above.
3. The Orchestrator (or merge reviewer) aggregates. Any Critical/High/Medium from any reviewer → gate FAILs.

### Devil's Advocate (anti-sycophancy)
A **unanimous PASS is suspicious**, not reassuring — independent AI reviewers tend to converge and rubber-stamp.

> When all reviewers return PASS with no Critical/High/Medium findings, the Orchestrator MUST spawn the `devils-advocate` agent before the gate is allowed to pass.

The Devil's Advocate assumes the artifact is guilty and hunts for what everyone missed. Its verdict:
- **UPHELD** — found a real Critical/High/Medium issue → gate FAILs, route to the fix lane.
- **CONFIRMED** — genuinely clean after adversarial effort → gate PASSes.

A gate reached by unanimous PASS is not PASS until the Devil's Advocate returns CONFIRMED. See `.claude/agents/devils-advocate.md`.

---

## 4. Where Gates Live (Example Pipeline)

| Gate | Phase | Pass criteria | Blind/Devil's? |
|------|-------|---------------|----------------|
| Spec/Dev-doc complete | 1–2 | Numbered reqs + acceptance criteria + dev-doc sections | No |
| EM approved | 1e | EM `APPROVED`, all reqs have an approach | No |
| Code review passed | 2c | Reviewer `APPROVED`, 0 Critical/High/Medium | No (single reviewer/lane) |
| Build green | 2b/2d | linter + type checker + unit tests pass | No |
| Test coverage verified | 3 | All acceptance criteria covered across lanes | **Yes** — senior testers blind, Devil's Advocate on unanimous PASS |
| Security clear | 5.4 | 0 Critical/High/Medium, no secrets, deps patched, policies enforced | No — `security-reviewer` + sub-scanners |
| Pipeline green | DevOps | CI valid, container/build artifacts healthy, runbook complete | No — see `devops-observability.md` |
| Observability ready | Observability | SLOs, health checks, alerts, structured logs | No — see `devops-observability.md` |

---

## 5. Process Signals (optional, lightweight)

Track these in `CONTINUITY.md` when running a full pipeline; they reveal a degrading process early:

| Signal | Healthy | Investigate |
|--------|---------|-------------|
| Gate first-pass rate | ≥ 80% | < 60% |
| Avg fix iterations per gate | ≤ 1.5 | > 3 |
| Defect-loop cycles per feature | ≤ 1 | 2 (then escalate) |

These are observability for the *process*, not a gate. Do not block on them.
