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
- A fabricated, assumed, or partial-output-based verdict — a PASS/FAIL not backed by the real, captured tool/agent output that proves it (see §2.5).

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

## 2.5. Evidence Requirement — a verdict must be backed by real output

A gate result is a claim about reality, so it must be grounded in reality. A PASS or FAIL — from a tester, a reviewer, a security scanner, or an agent reporting its own RARV Verify — is valid **only** when it cites the evidence that produced it: the command that ran and its captured output, or the specific finding (`file:line`) it rests on.

- **No invented or assumed results.** Never report a check as green without running it; never guess a scanner's output; never mark a gate PASS because it "should" pass. If you did not run it, you do not have a verdict — you have a TODO.
- **No premature verdicts from partial work.** Reading a still-running lane's in-progress output (or a single tester's report) and declaring the *gate* done is forbidden. A gate verdict requires every input it depends on to have actually completed and reported.
- **The proof travels with the handoff.** When an agent hands a verdict to the Orchestrator — or the Orchestrator records one in `CONTINUITY.md` — the command + output (or the finding list) goes with it. An uncited verdict is treated as unproven and the gate stays closed.

A fabricated, assumed, or partial-output-based verdict is an **auto-Critical** finding (§1): it defeats every downstream gate that trusts it. This is the gate-level form of the RARV rule "Verify means run it, not imagine it" (`.claude/rules/rarv-cycle.md`).

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

> When all reviewers return PASS with no Critical/High/Medium findings, the Orchestrator MUST spawn the `devils-advocate` agent before the gate is allowed to pass — **in any profile that installs it** (standard and enterprise). The **lean** profile's fast track omits this adversarial pass and does not install the agent.

The Devil's Advocate assumes the artifact is guilty and hunts for what everyone missed. Its verdict:
- **UPHELD** — found a real Critical/High/Medium issue → gate FAILs, route to the fix lane.
- **CONFIRMED** — genuinely clean after adversarial effort → gate PASSes.

Where the agent is installed, a gate reached by unanimous PASS is not PASS until the Devil's Advocate returns CONFIRMED. See `.claude/agents/devils-advocate.md` (present in the standard and enterprise profiles).

### Devil's Advocate on the plan (standard+)

The same adversarial pass also runs **once on the plan** — the spec + developer documentation — before EM approval is final, in any profile that installs the agent (standard and enterprise). It challenges the plan's assumptions: the weakest or most-volatile requirement, an untestable acceptance criterion, a hidden dependency, a missing requirement, and unjustified scope. An **UPHELD** verdict routes back to the Spec / Dev Doc Writer and the spec gate stays open until **CONFIRMED**. The **lean** fast track omits this pass; the Spec Writer's own self-critique (its RARV cycle) is the safeguard there. This is the planning-phase counterpart of the gate critique above — catching a flawed plan on paper is far cheaper than catching it after implementation.

---

## 4. Where Gates Live (Example Pipeline)

| Gate | Phase | Pass criteria | Blind/Devil's? |
|------|-------|---------------|----------------|
| Spec/Dev-doc complete | 1–2 | Numbered reqs + acceptance criteria + dev-doc sections | No |
| EM approved | 1e | EM `APPROVED`, all reqs have an approach; in standard+ not final until the plan critique CONFIRMS | **Yes (standard+)** — `devils-advocate` on the plan before approval |
| Code review passed | 2c | Reviewer `APPROVED`, 0 Critical/High/Medium | No (single reviewer/lane) |
| Build green | 2b/2d | linter + type checker + unit tests pass | No |
| Test coverage verified | 3 | All acceptance criteria covered across lanes | **Yes** — senior testers blind, Devil's Advocate on unanimous PASS |
| Security clear | 5.4 | 0 Critical/High/Medium, no secrets, deps patched, policies enforced | No — `security-reviewer` + sub-scanners |
| Pipeline green | DevOps | CI valid, container/build artifacts healthy, runbook complete | No — see `devops-observability.md` |
| Observability ready | Observability | SLOs, health checks, alerts, structured logs + (for hot backend paths) a load run meets the SLO | No — see `devops-observability.md` |
| Contract clear *(standard+; API stacks)* | Pre-merge | API contract diff vs base branch: 0 backward-incompatible deltas without an approved migration note + version bump; self-skips when no contract surface | No — `merge-reviewer` |
| Accessibility clear *(org · `regulated` strictness; UI stacks)* | Acceptance | WCAG-AA review of changed UI (keyboard, focus, semantics/ARIA, contrast, labels) via the `accessibility-review` skill: 0 Critical/High/Medium; self-skips when no UI surface | No — `acceptance-reviewer` |

---

## 5. Process Signals (optional, lightweight)

Track these in `CONTINUITY.md` when running a full pipeline; they reveal a degrading process early:

| Signal | Healthy | Investigate |
|--------|---------|-------------|
| Gate first-pass rate | ≥ 80% | < 60% |
| Avg fix iterations per gate | ≤ 1.5 | > 3 |
| Defect-loop cycles per feature | ≤ 1 | 2 (then escalate) |

These are observability for the *process*, not a gate. Do not block on them.
