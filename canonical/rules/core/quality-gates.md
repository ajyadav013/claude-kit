# Quality Gates, Severity & Blind Review

**An ordinary PASS requires zero open Critical/High/Medium — and every resolution needs proof.**

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
| **Medium** | Minor bug, code smell, perf issue, missing edge-case handling | BLOCK ordinary PASS — fix, or use a distinct structured accepted-risk resolution |
| **Low** | Style nit, minor naming, non-blocking doc gap | Note as TODO — does not block |
| **Cosmetic** | Formatting, wording preference | Informational — no action required |

**Blocking rule:** an ordinary gate **PASS** requires zero Critical, zero High, and zero Medium
findings. Low/Cosmetic may pass with notes. Critical and High are never waivable. A human may
explicitly accept a Medium finding through the structured **ACCEPTED RISK** transition in §2; that
resolution is visible and auditable, and is never relabelled PASS.

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

Review verdicts remain binary: **PASS** or **FAIL**. The lifecycle records one explicit gate
resolution: `passed`, a catalog-authorized `not-applicable`, or a human `accepted-risk` for Medium
findings. `failed` and `aborted` do not advance the run.

```
Phase completes -> Gate
  PASS  -> advance to next phase
  FAIL  -> fix highest-severity findings first
        -> the miss is logged to state://continuity (and agent-memory if durable)
        -> retry the gate
  retries exhausted -> escalate to human with unresolved findings
```

**Retry budgets** (already in `mandatory-workflow.md`; restated for one place):
- Planning review: **one initial blind panel + at most one consolidated revision/recheck**
- Code review: **2 targeted revisions** · Merge reviewer: 2 · Defect loop: 2 cycles

When a gate FAILs, the miss is recorded in `state://continuity` under **Mistakes & Learnings** so the
same defect is not reintroduced on retry. Read-only gate agents don't write it themselves: they
**return the miss in their handoff** and the Orchestrator records it (the scribe pattern — the
same handoff that carries the evidence, §2.5).

**Total planning-chain budget.** A planning generation is one content digest of the spec, design,
and developer documentation. Run one blind specialist panel on generation 1, make at most one
consolidated revision, then target-recheck only the owners of findings affected in generation 2.
Never start generation 3 automatically. The budget is shared by the panel; it is not multiplied by
the number of reviewers. Exhaustion is a checkpoint-and-escalate human decision
(`rule://human-in-the-loop`), never a weaker PASS.

**At escalation, the human's options are explicit.** Route a fix (re-open the lane), or accept each
residual **Medium** through a structured record:
`{{ provider.executable.cli }} pipeline accept-risk <gate> --finding-id <id> --reason '<why>' --accepted-by <person>
--owner <role> --ticket <id> --revisit '<trigger>' --evidence <file>`. The acceptance is bound to
the exact finding, gate, acceptance-evidence hash, recorded finding-set digest, Medium count,
repository commit, and gate-policy digest;
`status`, JSON output, and the final evidence summary label it **ACCEPTED RISK**, never PASS. A
commit, evidence, identity/count, or policy change makes it stale. Re-attestation is explicit with
`--refresh` (and `--supersedes-finding-id` when an identity changed); superseded records remain in
audit history. **Critical and High findings have no acceptance transition.** `--force` cannot waive
a finding or bypass gate order.

---

## 2.5. Evidence Requirement — a verdict must be backed by real output

A gate result is a claim about reality, so it must be grounded in reality. A PASS or FAIL — from a tester, a reviewer, a security scanner, or an agent reporting its own RARV Verify — is valid **only** when it cites the evidence that produced it: the command that ran and its captured output, or the specific finding (`file:line`) it rests on.

- **No invented or assumed results.** Never report a check as green without running it; never guess a scanner's output; never mark a gate PASS because it "should" pass. If you did not run it, you do not have a verdict — you have a TODO.
- **No premature verdicts from partial work.** Reading a still-running lane's in-progress output (or a single tester's report) and declaring the *gate* done is forbidden. A gate verdict requires every input it depends on to have actually completed and reported.
- **The proof travels with the handoff.** When an agent hands a verdict to the Orchestrator — or the Orchestrator records one in `state://continuity` — the command + output (or the finding list) goes with it. An uncited verdict is treated as unproven and the gate stays closed.

A fabricated, assumed, or partial-output-based verdict is an **auto-Critical** finding (§1): it defeats every downstream gate that trusts it. This is the gate-level form of the RARV rule "Verify means run it, not imagine it" (`rule://rarv-cycle`).

**Bounded handoff — the header is what the Orchestrator reads.** Every reviewer/tester/scanner
handoff leads with a bounded header: the verdict line, severity counts, the findings table
(`file:line` per finding), and the evidence citations — the command with its captured exit/summary
line, or the path to an evidence file under `state://workflow/`. The full report body follows below a
`--- FULL REPORT ---` marker: the Orchestrator persists it verbatim to its canonical path (the
scribe pattern) and does **not** re-read or re-analyze it — gate reasoning happens on the header.
Evidence cited by persisted path still satisfies "the proof travels with the handoff": the ledger
hashes the file, so the verdict stays provable without the full output transiting a second context.

**The Orchestrator's independent VALIDATE is mechanical — and nothing more.** The VALIDATE step
([4v] in the pipeline) is exactly: the project's test/lint/build commands the Orchestrator re-ran
itself (exit codes captured), `git diff --name-only` compared against the story's declared file
scope, and *recording* the coverage number when the suite already prints one (recording — never a
second coverage gate). Re-deriving the reviewer's work — reading diffs line by line, hand-built
content proofs, independent correctness analysis — is a routing error, not extra rigor: diff-level
correctness belongs to the Code Reviewer, and duplicating it spends the pipeline's scarcest
resource (the Orchestrator's context) to catch nothing the reviewer doesn't. This bounds *depth*,
never *effort*: the independent re-run itself and this section's evidence rule stand unchanged.

**Record the verdict through the schema-v2 lifecycle.** Start a new run with `{{ provider.executable.cli }} pipeline
start --task '<task>'`, or use `adopt` with a starting gate, reason, and adopter when work genuinely
predates the ledger. Before every gate resolution, persist the exact Critical/High/Medium/Low/
Cosmetic counts and their project-contained report with `record-findings --critical <n> --high <n>
--medium <n> --low <n> --cosmetic <n> --evidence <file>`; start's zeros are unverified placeholders,
not a clean result. Record an ordinary PASS with `close-gate <gate> --evidence <file>`. Record a
conditional gate only when its catalog condition applies, using `not-applicable <gate> --condition
<id> --reason '<why>' --evidence <file>`. Use `accept-risk` only for structured Medium acceptance,
then `complete` after every gate resolves. The CLI enforces order and policy, hashes gate and
finding-set evidence, binds the run to its repository/branch/commit and installed gate digest, and
writes atomically. Starting or adopting later work validates and hash-archives the prior terminal
snapshot; it never overwrites an active run.
Never hand-edit `gate_history` or manufacture a snapshot. Legacy v1 `skipped`/`overridden` entries
remain readable with warnings but are not legal new transitions; migrate deliberately with
`pipeline adopt`. If the installed CLI lacks this lifecycle, report the version mismatch and block
until the project is upgraded—manual JSON is not an equivalent trust boundary.

**If a lifecycle write fails, say so—never complete quietly without one.** Retry only after fixing
the named safe-path, permissions, lock, or version problem. If it still fails, report the gate as
**BLOCKED** with the operation, path, and error. Do not bypass atomic/locked writes by editing the
snapshot. The absence of a valid ledger must remain noticeable.

**Self-check before recording any verdict:** can I point to the captured command output or the `file:line` finding behind this PASS/FAIL? If not, it is a TODO, not a verdict — leave the gate closed.

### Evidence reuse and invalidation

Do not rerun an expensive deterministic check merely because another persona reached a later
stage. Evidence from the current run may be cited again only when its reuse key matches exactly:
command and arguments, working directory, relevant source/test/config/lockfile content digests,
toolchain versions, and material environment identity. A changed key invalidates the evidence.
External or E2E evidence additionally binds the target identity, seeded state, and a declared TTL.

Focused checks stay focused. Run one authoritative full merged suite at the final integration or
release boundary; pre-merge lane evidence cannot masquerade as that suite. After it passes, PR
preparation cites the same content-addressed result when the key is unchanged instead of running it
again. When reuse is uncertain or the capture is incomplete, rerun — never infer PASS. Record the
key beside the command output so reuse is auditable rather than conversational.

---

## 3. Blind Review + Devil's Advocate

Applies wherever **multiple reviewers assess the same artifact in parallel** — primarily:
- the **test-coverage merge gate** (multiple independent test lanes feeding the merge reviewer), and
- any **multi-reviewer review phase** the Orchestrator runs in parallel.

### Planning convergence contract

The planning review is a **panel, not a negotiation**. Freeze one planning generation (artifact
paths + content digest), then dispatch every applicable specialist against that exact generation in
parallel: frontend feasibility, backend feasibility, cross-system architecture, and the conditional
Devil's Advocate challenge. Reviewers do not see or respond to one another. The Engineering Manager
receives the completed panel once, de-duplicates its findings, applies the authority table below,
and returns one consolidated decision to the writer. Do not run role-to-role reply chains and do not
wait for unanimity.

Every planning finding has these fields; an omission makes the verdict incomplete rather than FAIL:

```text
finding-id | severity | authority-domain | criterion | evidence |
requested-correction | owner | disposition
```

`authority-domain` is exactly one of `product`, `frontend`, `backend`, `architecture`, `delivery`,
or `gate-evidence`; the stable vocabulary makes ownership machine-checkable across reviewers.

IDs remain stable across generations. Before a revision is dispatched, duplicates are merged by
violated criterion/invariant plus evidence location. A reviewer may block only on an evidenced
Critical/High/Medium defect. A preference, stylistic alternative, speculative future improvement,
or scope addition is non-blocking and is recorded as an ADR candidate or backlog item. Low,
Cosmetic, and advisory notes never cause a new planning generation.

**Decision rights — no votes:**

| Question | Decider |
|---|---|
| Product intent, scope, or ambiguous acceptance behavior | Human/product owner; agents stop and ask |
| Frontend or backend feasibility inside one stack | The corresponding senior planning reviewer |
| Cross-system interfaces, boundaries, and non-functional invariants | Technical Architect |
| Sequencing, ownership, staffing, and reversible delivery trade-offs | Engineering Manager |
| Correctness, security, policy, or acceptance evidence | The owning deterministic gate; no persona may override it |
| Adversarial challenge | Devil's Advocate may open an evidenced blocker, but has no stylistic veto and may not expand scope |

When two valid approaches remain, the Engineering Manager selects the simplest reversible option
that satisfies the frozen contract and records a stable decision ID, authority domain, selected
option, rejected alternatives, rationale, strongest dissent, accountable decider, evidence, and
concrete reopen trigger. An empty decision ledger is valid only when no alternative or disagreement
was adjudicated.
An accepted decision reopens only for new evidence, a violated invariant, a human scope change, or a
changed artifact in the decider's owned domain. Rephrased preference is not new evidence.

**Strict-progress rule.** After the single revision, every prior blocking ID must be exactly
`fixed`, `disputed`, or `human-required`. Continue automatically only when the open blocking set is
a strict subset of the previous set, with no renamed/new blocker, reopened blocker, or severity
escalation. An unchanged artifact digest, unchanged normalized blocker set, dispute, new blocker,
reopen, or escalation is a no-progress/conflict checkpoint: persist the artifact and finding
register and ask the human once. Never spend another autonomous review cycle trying to manufacture
agreement. A targeted recheck examines its assigned prior IDs only unless the artifact changed in
that reviewer's authority domain.

### Blind review
1. Reviewers assess **independently** — each gets the same frozen artifact + spec + rules, none sees another's findings until all have reported.
2. Each returns a structured verdict: `PASS | FAIL` + findings classified by the severity model above.
3. The Orchestrator (or merge reviewer) aggregates and de-duplicates before routing. Any evidenced Critical/High/Medium from any reviewer → gate FAILs.

### Devil's Advocate (anti-sycophancy)
A **unanimous PASS is suspicious**, not reassuring — independent AI reviewers tend to converge and rubber-stamp.

> When all reviewers return PASS with no Critical/High/Medium findings, the Orchestrator MUST spawn the `devils-advocate` agent before the gate is allowed to pass — **in any profile that installs it** (standard and enterprise). The **lean** profile's fast track omits this adversarial pass and does not install the agent.

**Planning exception:** the planning review panel already includes the Devil's Advocate once when
its risk/uncertainty condition applies. Do not dispatch a second post-unanimity adversarial pass for
that panel. The rule above applies to other eligible multi-reviewer gates, such as test coverage.

The Devil's Advocate assumes the artifact is guilty and hunts for what everyone missed. Its verdict:
- **UPHELD** — found a real Critical/High/Medium issue → gate FAILs, route to the fix lane.
- **CONFIRMED-WITH-COSTS** — no blocking finding, but a durable cost worth recording → gate PASSes.
- **CONFIRMED** — genuinely clean after adversarial effort → gate PASSes.

Outside the planning exception, where the agent is installed, a gate reached by unanimous PASS is
not PASS until the Devil's Advocate returns CONFIRMED or CONFIRMED-WITH-COSTS. See
`agent://devils-advocate` (present in the standard and enterprise profiles).

Every verdict also carries a **premortem** (assume it shipped and failed — the likeliest cause and the earliest signal) and a **balance sheet** (what the approach gets right, and what it costs). A critique that only lists defects cannot be weighed against doing nothing, and leaves no record of *why* an accepted downside was accepted.

**CONFIRMED-WITH-COSTS is not a soft UPHELD.** It never carries a Critical/High/Medium — anything blocking is UPHELD. Each recorded cost names an accepting role and a concrete revisit trigger, and the Orchestrator writes it to `state://continuity` so it survives the gate that accepted it. A cost with no owner or no trigger is a hedge, not a cost: it is dropped and the verdict is plain CONFIRMED. Where the project keeps ADRs, a cost that shapes the architecture belongs in one (see `rule://documentation`).

### Devil's Advocate on the plan (standard+)

The same adversarial pass also runs **once in the blind planning panel** — on the spec + developer
documentation — before EM adjudication is final, in any profile that installs the agent (standard
and enterprise) and when risk or uncertainty is present. It challenges the plan's assumptions: the
weakest or most-volatile requirement, an untestable acceptance criterion, a hidden dependency, a
missing requirement, and unjustified scope. Its premortem is the highest-value part of this pass —
the cheapest moment to ask "assume we built this and it failed" is before anyone has built it. An
**UPHELD** verdict contributes stable findings to the panel register; it does not start a private
Devil's Advocate/writer loop. On generation 2 it rechecks only its assigned prior IDs unless its
authority-domain input changed. The **lean** fast track omits this pass; the Spec Writer's own
self-critique (its RARV cycle) is the safeguard there.

---

## 4. Where Gates Live (Example Pipeline)

| Gate | Phase | Pass criteria | Blind/Devil's? |
|------|-------|---------------|----------------|
| Spec/Dev-doc complete | 1–2 | Numbered reqs + acceptance criteria + dev-doc sections | No |
| EM approved | 1e–1e.5 | One EM `PASS` over the de-duplicated blind specialist panel; zero Critical/High/Medium | **Yes (conditional, standard+)** — `devils-advocate` joins the same frozen-plan panel |
| Code review passed | 2c | Reviewer `APPROVED`, 0 Critical/High/Medium | No (single reviewer/lane) |
| Build green | 2b/2d | linter + type checker + unit tests pass | No |
| Test coverage verified | 3 | All acceptance criteria covered across lanes | **Yes** — senior testers blind, Devil's Advocate on unanimous PASS |
| Security clear | 5.4 | 0 Critical/High/Medium, no secrets, deps patched, policies enforced | No — `security-reviewer` + sub-scanners |
| Pipeline green | DevOps | CI valid, container/build artifacts healthy, runbook complete | No — see `devops-observability.md` |
| Observability ready | Observability | SLOs, health checks, alerts, structured logs + (for hot backend paths) a load run meets the SLO | No — see `devops-observability.md` |
| Contract clear *(standard+; API stacks)* | Pre-merge | API contract diff vs base branch: 0 backward-incompatible deltas without an approved migration note + version bump; otherwise evidenced `not-applicable` only for the configured no-contract condition | No — `merge-reviewer` |
| Accessibility clear *(org · `regulated` strictness; UI stacks)* | Acceptance | WCAG-AA review of changed UI (keyboard, focus, semantics/ARIA, contrast, labels) via the `accessibility-review` skill: 0 Critical/High/Medium; otherwise evidenced `not-applicable` only for the configured no-UI condition | No — `acceptance-reviewer` |

---

## 5. Process Signals (optional, lightweight)

Track these in `state://continuity` when running a full pipeline; they reveal a degrading process early:

| Signal | Healthy | Investigate |
|--------|---------|-------------|
| Gate first-pass rate | ≥ 80% | < 60% |
| Avg fix iterations per gate | ≤ 1.5 | > 3 |
| Defect-loop cycles per feature | ≤ 1 | 2 (then escalate) |

These are observability for the *process*, not a gate. Do not block on them.

---

**This rule is working if** no ordinary PASS carries an open Critical/High/Medium, every Medium
acceptance remains visibly distinct and current, no verdict ships without its evidence, and a
unanimous PASS always saw the Devil's Advocate before it counted.
