# Pipeline Speed (0.82.0) Implementation Plan

> **Historical completed plan — superseded in 0.83.0.** The commands and manual state-editing
> fallbacks below describe the old schema-1 lifecycle and are unsafe for current runs. Follow
> [`docs/pipeline-speed-playbook.md`](../../pipeline-speed-playbook.md): record exact findings, use
> structured `accept-risk` only for Medium findings, and never hand-write the snapshot.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the 12 verified pipeline-speed adoptions from `docs/superpowers/specs/2026-08-17-pipeline-speed-design.md` as claude-kit 0.82.0, plus an operator playbook, fully tested.

**Architecture:** Prose-only payload change — bounded edits to 13 existing payload files (rules/agents/skills) + 1 new repo doc (playbook, NOT bundled) + 5-place version bump + CHANGELOG. No new rules/agents/hooks/catalog entries. Net-≤+5-lines on `agents/orchestrator.md`.

**Tech Stack:** Markdown payload prose; verification via the repo's deterministic checkers (pytest, ruff, mypy, shellcheck, gen_hooks --check, docs-consistency, cross-refs --strict, skill-descriptions --strict, rule-sizes) + build/twine + init smoke.

## Global Constraints

- Branch: `feat/pipeline-speed` (off main @ 3e70b4e). PR #107 (0.81.0) merges FIRST when the user is ready; then rebase and keep 0.82.0 + both CHANGELOG entries.
- NEVER `git add -A` — stage every file by name and verify with `git status --short` before commit.
- Every commit ends with trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Python tools via `.venv/bin/*` (hooks block bare `python`/`pip`).
- Stack-agnostic core: no Docker/framework terms in `rules/ agents/ skills/` additions (guard grep in Task 9).
- Gate semantics are never weakened: zero Critical/High/Medium to PASS stands everywhere; the waiver is the existing audited override, never a new PASS condition.
- All new cross-references must point at files that exist (checked by `check_cross_references.py --strict`).
- `df -h` before pytest/build; < 1 Gi free → STOP.

---

### Task 1: quality-gates.md — total budget, waiver wiring, bounded handoff, mechanical VALIDATE

**Files:**
- Modify: `rules/quality-gates.md` (§2 after retry budgets ~line 55; §2.5 after the fabricated-verdict paragraph ~line 72)

**Interfaces:**
- Produces: section names other tasks cross-reference verbatim — "Bounded handoff" and "the Orchestrator's VALIDATE is mechanical" (§2.5), and the escalation/waiver paragraph (§2) that `human-in-the-loop.md` (Task 5) and the playbook (Task 7) cite as `` `.claude/rules/quality-gates.md` §2 ``.

- [ ] **Step 1: §2 — insert after the retry-budgets block** (anchor: the paragraph ending "…the same defect is not reintroduced on retry. … (the scribe pattern — the same handoff that carries the evidence, §2.5)." — insert AFTER that paragraph, before the `---` that precedes §2.5):

```markdown
**Total planning-chain budget.** The retry budgets above are per reviewer; runs die by the tail, not
the caps. Across the whole planning chain (stages 1c–1e.5 — spec, dev docs, EM review, plan
critique), allow at most **2 full re-review generations**: after the second full pass over the
chain's findings, do not start a third. Late rounds tend to close every earlier finding and mint new
ones from their own new prose — the budget converts that tail into a human decision
(`.claude/rules/human-in-the-loop.md`, exhausted budgets).

**At escalation, the human's options are explicit.** Route a fix (re-open the lane) — or accept a
residual **Medium** as a recorded known gap through the audited override that already exists:
`claude-kit pipeline close-gate <gate> --force --override-reason '<finding>: accepted known gap —
owner: <role>, revisit: <trigger>'`. The override is loud by design: the ledger records status
`overridden` and `claude-kit pipeline validate` / `status` WARN on it forever after. Name an owner
and a revisit trigger in the reason — the CONFIRMED-WITH-COSTS cost-record shape (§3); a waiver with
neither is a hedge, not a decision. **Critical and High findings are never waived this way.** None
of this changes gate semantics: an autonomous PASS still requires zero Critical/High/Medium — the
waiver is a human decision recorded as an override, never a new kind of PASS.
```

- [ ] **Step 2: §2.5 — insert after the fabricated-verdict paragraph** (anchor: the paragraph ending "…the gate-level form of the RARV rule "Verify means run it, not imagine it" (`.claude/rules/rarv-cycle.md`)." — insert AFTER it, before "**Record the verdict in the deterministic ledger.**"):

```markdown
**Bounded handoff — the header is what the Orchestrator reads.** Every reviewer/tester/scanner
handoff leads with a bounded header: the verdict line, severity counts, the findings table
(`file:line` per finding), and the evidence citations — the command with its captured exit/summary
line, or the path to an evidence file under `.claude/state/`. The full report body follows below a
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
```

- [ ] **Step 3: Verify** — `.venv/bin/python scripts/check_rule_sizes.py && .venv/bin/python scripts/check_cross_references.py --strict` → both exit 0.
- [ ] **Step 4: Commit** — `git add rules/quality-gates.md` → `git commit -m "feat(rules): planning-chain budget + audited-waiver wiring + bounded handoff + mechanical VALIDATE bound (quality-gates)"` (+ trailer).

---

### Task 2: orchestrator.md — four minimal touches (net ≤ +5 lines)

**Files:**
- Modify: `agents/orchestrator.md:12` (scribe), `:334-341` (Stage SP), `:383-395` ([4a-FE]/[4v-FE]), `:413` ([4a-BE])

**Interfaces:**
- Consumes: §2.5 section names from Task 1.

- [ ] **Step 1: line 12** — change `you persist their returned reports verbatim to their canonical paths, and record their verdicts` → `you persist their returned reports verbatim to their canonical paths **without re-analyzing them** (bounded handoff — `.claude/rules/quality-gates.md` §2.5), and record their verdicts`
- [ ] **Step 2: [4v-FE] block** — change `The lane does not reach the Code Reviewer until *your own* run is green.` → `The lane does not reach the Code Reviewer until *your own* run is green — and VALIDATE is exactly this, nothing deeper: diff-level correctness is [4b]'s job (`.claude/rules/quality-gates.md` §2.5, "mechanical — and nothing more").`
- [ ] **Step 3: [4a-FE] Input fix** — change `- **Input**: Approved spec + design spec.` → `- **Input**: the story under implementation — its declared file scope + acceptance criteria — with the approved spec + design spec as reference (one story per dispatch; `.claude/rules/mandatory-workflow.md` Phase 2).` And [4a-BE]: `- **Input**: Approved backend spec.` → `- **Input**: the backend story under implementation (file scope + criteria), with the approved backend spec as reference.`
- [ ] **Step 4: Stage SP** — after the sentence `The story breakdown then drives lane assignment at Fork Point 2.` append: `Carry each story's **risk / batchable** tags into routing: low-risk stories take the reduced chain and up to 3 batchable stories may share one dispatch (`.claude/rules/risk-classification.md` → Story-level routing; `.claude/rules/mandatory-workflow.md` §1f).`
- [ ] **Step 5: Verify + Commit** — `wc -l agents/orchestrator.md` (must be ≤ 859); cross-refs check; `git add agents/orchestrator.md` → commit `"feat(agents): orchestrator — bounded scribe, VALIDATE depth bound, story-scoped dispatch input, SP routing hook"`.

---

### Task 3: story-planner.md + risk-classification.md + mandatory-workflow.md

**Files:**
- Modify: `agents/story-planner.md` (Outputs item 1 & 4, Constraints)
- Modify: `rules/risk-classification.md` (new section after "Sensitive areas")
- Modify: `rules/mandatory-workflow.md` (§1f end, Phase 2 header)

**Interfaces:**
- Produces: the tag vocabulary `risk: low | standard` and `batchable: true`, and the section name "Story-level routing" — used verbatim by Tasks 2, 4, 7.

- [ ] **Step 1: story-planner Outputs item 1** — change `…and the files/modules it touches. Keep each story small enough for one focused implementation pass.` → `…and the files/modules it touches, plus two routing tags: **risk** (`low` | `standard` — `low` only when the story is local, reversible, and touches no sensitive area per `.claude/rules/risk-classification.md`; when in doubt, `standard`) and **batchable** (`true` only for mechanical low-risk stories — docs, changelog, packaging, examples, version bumps). Keep each story small enough for one focused implementation pass — each story is the unit of **one dispatch**.`
- [ ] **Step 2: story-planner Outputs item 4** — change `4. **Sequencing** — a suggested order for the rest, with the join points where a Merge Reviewer is needed (shared API contract, shared data model).` → same sentence plus: ` Sequence one thin **end-to-end slice early**: every later story then validates against a running system instead of prose — the slice *is* the foundation; build it first, then widen.`
- [ ] **Step 3: risk-classification.md** — insert after the "## Sensitive areas → at least **high**" section, before "## High-risk protocol":

```markdown
## Story-level routing (inside a feature run)

Once a spec is broken into stories, the tier also allocates **ceremony per story**: a **low**-risk
story (tagged by the story planner) routes through the reduced chain — developer → code reviewer →
tester — while its siblings keep the full chain. Three things never move with the tier: run-level
gates still apply to the merged output (zero Critical/High/Medium — `.claude/rules/quality-gates.md`);
specialist routing in `.claude/rules/mandatory-workflow.md` still triggers on the **surface
touched, never story size** (a "low-risk" story that edits a query, auth, or secrets is at least
**high** — see the sensitive areas above); and code review itself is never skipped. This is not a
lowered bar: the tier decides **which agents spawn for the story**, never what passes a gate.
```

- [ ] **Step 4: mandatory-workflow §1f** — after the **Gate:** line of 1f (`…Implementation CANNOT start until coverage is complete.`), append a new paragraph:

```markdown
The breakdown also drives two throughput decisions. **Story groups:** a *story group* is a maximal
dependency-connected set of stories whose combined file boundary is disjoint from every other
group's; two or more immediately-startable groups are the trigger for orchestrator-per-group
fan-out (`.claude/skills/sdlc/SKILL.md` → Story-group fan-out). **Batching:** up to **3** stories
tagged `batchable` (mechanical, low-risk — docs, changelog, packaging) sharing a disjoint combined
boundary may share one developer dispatch and one review pass — same stages, **one commit per
story**, never stage-skipping. Every story keeps its own risk tag
(`.claude/rules/risk-classification.md` → Story-level routing) and its own ticket (1g).
```

- [ ] **Step 5: mandatory-workflow Phase 2 header** — directly under `# Phase 2 — Development (Stages 4-5)`, insert:

```markdown
**Dispatch sizing (default):** prefer **one story per implementation dispatch** — a crash or
compaction then loses at most one story of un-persisted work, and the CONTINUITY + snapshot writes
at each stage transition make the resume cheap (`.claude/rules/continuity.md`). Calibrate to story
size rather than a magic count; batched `batchable` stories (§1f) are the deliberate exception.
```

- [ ] **Step 6: Verify + Commit** — rule-sizes + cross-refs checks; `git add agents/story-planner.md rules/risk-classification.md rules/mandatory-workflow.md` → commit `"feat(rules): per-story risk routing, batchable stories, story groups, slice-early sequencing, dispatch sizing"`.

---

### Task 4: sdlc SKILL fan-out + continuity cross-ref + orchestration-patterns reconciliation

**Files:**
- Modify: `skills/sdlc/SKILL.md` (step-3 items 1 & 3; new subsection after the numbered list)
- Modify: `rules/continuity.md` (§Concurrency bullet 2)
- Modify: `skills/_references/orchestration-patterns.md` (§D "What to do instead")

**Interfaces:**
- Consumes: "Story-level routing", story-group definition (Task 3), "Probe before fan-out" (Task 5 — forward reference is fine, both land before release checks).
- Produces: subsection title "Story-group fan-out" cited by Tasks 3, 7.

- [ ] **Step 1: SKILL.md §3 item 1** — append to the classification item (after `…see that rule's "Native dynamic workflows as the wave substrate".)`): `Have the story planner tag each story (risk / batchable); low-risk stories inside a full run route through the reduced chain per `.claude/rules/risk-classification.md` → Story-level routing.`
- [ ] **Step 2: SKILL.md §3 item 3** — append after `…so the human can veto the scale before tokens are spent.`: `Before the run's first fan-out, **probe** each planned model tier with one trivial spawn and fall back per `.claude/rules/model-tiers.md` → "Probe before fan-out".`
- [ ] **Step 3: SKILL.md — new subsection** after the numbered list of §3 (before `## 4. Stop for the human where required`):

```markdown
### Story-group fan-out (optional, feature scale)

When the story breakdown yields **two or more immediately-startable story groups** (maximal
dependency-connected story sets with mutually disjoint file boundaries —
`.claude/rules/mandatory-workflow.md` §1f) and the run is not program-scale (Mode E), parallelize
across context windows instead of inside one: spawn **one orchestrator per group**, each in its
**own git worktree** per `.claude/rules/continuity.md` → Concurrency — each worktree carries its own
CONTINUITY.md, snapshot, and gate ledger, authoritative for that group's per-story gates. Announce
the scale first (N orchestrators × model tiers) so the human can veto it. Merge in dependency
order, one group at a time, with **human approval per mainline merge** (workers propose; humans
approve), then run the run-level gates — test-coverage across groups, security-clear on the merged
output — in the primary checkout, recorded in its ledger. A group that fails escalates per the
normal retry protocol; healthy groups still merge; a failed group's stories return to the backlog —
never merge a group whose gates didn't pass.
```

- [ ] **Step 4: continuity.md §Concurrency bullet 2** — append: ` This is also the substrate for **story-group fan-out**: the `sdlc` entrypoint may run one orchestrator per disjoint story group, one worktree each (`.claude/skills/sdlc/SKILL.md`).`
- [ ] **Step 5: orchestration-patterns.md §D** — change `**What to do instead:** keep the orchestration depth at most 1 (slash command → personas). The merge happens in the main agent.` → same, plus: ` (Deliberate exception: the `sdlc` pipeline's contract — main session → orchestrator(s) → workers — carries its depth by design; this anti-pattern targets ad-hoc persona trees, not that contract.)`
- [ ] **Step 6: Verify + Commit** — `.venv/bin/python scripts/check_skill_descriptions.py --strict` (description untouched — must still pass) + cross-refs; `git add skills/sdlc/SKILL.md rules/continuity.md skills/_references/orchestration-patterns.md` → commit `"feat(skills): story-group fan-out in sdlc entrypoint + concurrency cross-ref + depth-1 reconciliation"`.

---

### Task 5: model-tiers probe + agent-resilience fallback row + human-in-the-loop wiring

**Files:**
- Modify: `rules/model-tiers.md` (new subsection after "## Notes")
- Modify: `rules/agent-resilience.md` (Fallback row)
- Modify: `rules/human-in-the-loop.md` (Exhausted-budgets row; new paragraph after the interview-me line)

**Interfaces:**
- Produces: subsection title "Probe before fan-out" (cited by Task 4 step 2 and Task 7).

- [ ] **Step 1: model-tiers.md** — insert after the "## Notes" bullet list, before "## When to escalate a tier":

```markdown
## Probe before fan-out

Tier availability is a property of the *deployment*, not the payload — an alias in frontmatter can
name a model the provider account doesn't serve, and the failure signature is an **instant,
zero-token spawn death**, easily mistaken for an agent bug. So before a run's **first** fan-out:
probe-spawn one trivial agent (a one-word reply) per model tier the run plans to use. A tier whose
probe dies instantly is unavailable here: **fall back one tier** (Fast → Default → Critical),
record the override in `CONTINUITY.md`, and keep it for the rest of the run — don't re-discover the
same failure lane by lane. The probe also doubles as the credential-freshness check for long runs:
verify auth by the probe's *behavior*, never by reading secrets or `.env`
(`.claude/rules/agent-guardrails.md`). Deployment-neutral by design — probe tiers, not provider
names.
```

- [ ] **Step 2: agent-resilience.md Fallback row** — change `| **Fallback** | A primary tool/source/path is unavailable | Have a defined alternative (another source, a simpler method, manual steps) and say you used it. |` → append to the discipline cell: ` A planned model tier that fails its pre-fan-out probe falls back one tier, recorded (`.claude/rules/model-tiers.md` → Probe before fan-out).`
- [ ] **Step 3: human-in-the-loop.md Exhausted-budgets row** — change the Examples cell `A review/defect loop hit its retry budget; a recovery loop exhausted its attempts (`.claude/rules/agent-resilience.md`); a gate fails and can't be resolved.` → append: ` At escalation the choices are explicit: route a fix, or accept a residual **Medium** as a recorded known gap via the audited override (`.claude/rules/quality-gates.md` §2) — Critical/High are never waived.`
- [ ] **Step 4: human-in-the-loop.md — batch the non-blocking asks** — insert after the `interview-me` paragraph (ending `…rather than firing a wall of questions.`):

```markdown
**Batch the non-blocking asks.** Every category in the stop table is a *blocking* ask — stop now,
synchronously. A question that does **not** block the current story (a naming preference, a nice-to-
have clarification, a future-scope choice) is queued instead: record it under **Open Questions** in
`CONTINUITY.md` and raise the whole queue as **one round at the next gate or join** — five answers
at a boundary beat five mid-build interruptions. Two carve-outs: intent-extraction interviews (1b,
`interview-me`) stay one-question-at-a-time by design, and anything in the stop table is never
queued.
```

- [ ] **Step 5: Verify + Commit** — rule-sizes + cross-refs; `git add rules/model-tiers.md rules/agent-resilience.md rules/human-in-the-loop.md` → commit `"feat(rules): tier probe before fan-out, probe-fallback row, waiver + question-batching wiring (HITL)"`.

---

### Task 6: spec evidence hygiene + warm test infra

**Files:**
- Modify: `agents/spec-doc-writer.md` (Quality Checklist)
- Modify: `rules/documentation.md` (§8)
- Modify: `skills/spec-driven-development/SKILL.md` ("Keeping the Spec Alive")
- Modify: `rules/testing.md` (after the Parallel Execution attribution blockquote)

- [ ] **Step 1: spec-doc-writer Quality Checklist** — add checklist item after `- [ ] Open questions are flagged for human resolution`: `- [ ] No executed evidence pasted in — command output and measurement blocks live at their `.claude/state/` or artifact path and are **cited by path**; the spec stays requirements-sized because every agent reads it`
- [ ] **Step 2: documentation.md §8** — after the bullet list ending `- Breaking change → note in PR description + README`, append: `A changelog note is one line; **executed evidence never lands in the spec** — command output, measurement prose, and gate proofs live at their `.claude/state/` or artifact path, cited by path (`.claude/rules/quality-gates.md` §2.5). Requirement and decision updates are always welcome in the spec; run logs are not.`
- [ ] **Step 3: spec-driven-development "Keeping the Spec Alive"** — add bullet after `- **Capture substantial changes as a delta…**`: `- **Cite evidence, never paste it** — executed output (test runs, measurements, gate proofs) lives at its `.claude/state/` or artifact path; the spec links, so it stays requirements-sized for every agent that reads it.`
- [ ] **Step 4: testing.md** — insert a new subsection after the gtest-parallel attribution blockquote (ending `…Re-derived in prose; not vendored.`), before `## Deterministic Simulation Testing`:

```markdown
## Keep Shared Test Services Warm Across Iterations

When the suite depends on long-lived shared services (a database, a queue, a browser runtime, an
app server), start them **once per run** and reuse them across test iterations and defect-loop
cycles — cold-starting the environment on every cycle taxes exactly the loop the pipeline iterates
most. Reuse composes with, never replaces, the isolation rules above: pair the warm service with
**per-test state reset** (truncate/flush/rollback), or the reuse licenses the shared mutable state
this file forbids. And it never waives the delivery gate: Pipeline Green still verifies a **clean
cold start** brings everything up healthy (`.claude/rules/devops-observability.md`). Suite-scoped
fixtures are the per-stack mechanism — see the project's testing conventions for the concrete form.
```

- [ ] **Step 5: Verify + Commit** — rule-sizes + cross-refs + `grep -rInE 'docker|compose|container' <the testing.md added block>` returns nothing; `git add agents/spec-doc-writer.md rules/documentation.md skills/spec-driven-development/SKILL.md rules/testing.md` → commit `"feat(rules): spec evidence hygiene (cite-by-path) + warm shared test services"`.

---

### Task 7: operator playbook (repo docs — NOT bundled)

**Files:**
- Create: `docs/pipeline-speed-playbook.md`

Content — write exactly (paste-ready recipes; each maps to a shipped 0.82.0 behavior so the doc self-obsoletes on upgrade):

```markdown
# Pipeline Speed Playbook — for in-flight runs (installs ≤ 0.81.0)

Run-level instructions that recover most of 0.82.0's speed levers **without upgrading**. Each
recipe says what to paste into your orchestrator dispatch (or run yourself). After
`claude-kit upgrade`, the payload carries all of this natively and this doc is obsolete.

## 1. Probe model tiers before any fan-out
Most agents pin `model: sonnet`/`opus` in frontmatter; if your deployment doesn't serve an alias,
the spawn dies **instantly with ~0 tokens**. Before the first fan-out, spawn one trivial agent per
tier ("reply with one word"). On instant death: pass an explicit `model:` override on **every**
dispatch for that run and note it in CONTINUITY.md. Re-probe each new session — availability flips.
Refresh credentials before long sessions (e.g. `! gcloud auth login --update-adc` on Vertex).

## 2. One story per dispatch + resume from the snapshot
Ask for one story per orchestrator invocation, not "stories 2–5". On crash, resume from
`.claude/state/pipeline-snapshot.json`: re-enter after `last_gate_passed`; never re-run passed
gates or re-apply committed edits.

## 3. Bound the orchestrator's own verification (paste into the dispatch)
> Your independent VALIDATE is exactly: re-run the test/lint/build commands (capture exit codes),
> `git diff --name-only` vs the story's declared file scope, record the printed coverage number.
> Nothing deeper — no line-by-line diff reading, no content proofs. The code reviewer owns
> correctness. Reviewer reports: read the verdict + severity counts + findings table only; persist
> the body verbatim without re-analyzing it.

## 4. Cap the review chain; waive residual Mediums loudly
State at dispatch: "2 full re-review generations, then escalate." At escalation, accept a residual
Medium as a known gap with the **audited** override (first probe your CLI:
`claude-kit pipeline close-gate --help | grep -q force` — a stale binary may lack it):
`claude-kit pipeline close-gate <gate> --force --override-reason '<finding>: accepted known gap — owner: <role>, revisit: <trigger>'`
`validate`/`status` will WARN on it forever — that's the point. Critical/High: never waive.
If the CLI lacks `--force`, hand-write the `gate_history` entry (schema: `.claude/rules/continuity.md`).

## 5. Fan out disjoint stories across orchestrators
When ≥2 unblocked stories have disjoint file boundaries: one orchestrator per story group, each in
its own `git worktree` (each gets its own CONTINUITY/snapshot). Merge in dependency order — you
approve each mainline merge — then run the run-level gates (test coverage, security) on the merged
output in the primary checkout.

## 6. Route ceremony by story risk; batch the mechanical tail
Low-risk stories (docs/changelog/packaging/config; nothing touching auth, queries, secrets,
tenancy, migrations): developer → code reviewer → tester only. Batch up to 3 of them into one
dispatch, one commit per story. Any story touching a sensitive surface gets the full chain — decide
by surface, never by size.

## 7. Keep the spec requirements-sized
Move executed-evidence blocks (command output, measurements) out of `docs/specs/*` into
`.claude/state/gate-evidence/`, leaving one-line citations. Every agent reads the spec on every
spawn — a 7,000-line spec is a per-spawn tax.

## 8. Two habits that round it out
Queue non-blocking questions in CONTINUITY "Open Questions"; raise them as one batch at the next
gate (blocking stops stay immediate). Start shared test services once per run and reuse across
defect-loop cycles (reset state between tests; the final clean-cold-start check still runs).

## What NOT to cut
Code review (it catches Criticals reading alone approves), the security pass on sensitive
surfaces, and the real-environment verification your project relies on. Speed comes from cutting
re-verification and idle ceremony — not verification.
```

- [ ] **Step 2: Commit** — `git add docs/pipeline-speed-playbook.md` → commit `"docs: pipeline-speed operator playbook for in-flight runs"`.

---

### Task 8: version bump ×5 + CHANGELOG

**Files:**
- Modify: `pyproject.toml` (`version = "0.80.0"` → `"0.82.0"`), `.claude-plugin/plugin.json` (`"version": "0.80.0"` → `"0.82.0"`), `.claude-plugin/marketplace.json` (same), `src/claude_kit/__init__.py` (`__version__ = "0.80.0"` → `"0.82.0"`), `SECURITY.md` (supported-version row → `0.82.x`), `CHANGELOG.md` (new entry atop `## [0.80.0]`)

Note: on this branch main-parity is 0.80.0. If PR #107 (0.81.0) merges first, rebase keeps ours at 0.82.0 and both CHANGELOG entries stack (0.82.0 above 0.81.0).

- [ ] **Step 1: CHANGELOG entry** (verbatim, date 2026-08-17):

```markdown
## [0.82.0] — 2026-08-17

Pipeline speed: three field-feedback sets from live SDLC runs (3 projects, 18 levers) triaged into
12 payload adoptions, each adversarially verified against the existing prose before adoption. The
organizing principle: the orchestrator's context window is the pipeline's scarce resource —
throughput = stories-per-window × concurrent-windows.

### Added
- **Bounded handoff contract** (`rules/quality-gates.md` §2.5): reviewer/tester/scanner handoffs
  lead with a verdict/severity/findings header; the orchestrator persists the full body verbatim
  without re-analyzing it.
- **Mechanical VALIDATE bound** (§2.5): [4v] is exit codes + scope diff + recorded coverage number
  — diff-level correctness explicitly belongs to the code reviewer.
- **Planning-chain total budget + audited waiver wiring** (§2): max 2 full re-review generations,
  then human escalation; residual Mediums acceptable only via the existing loud
  `close-gate --force --override-reason` path with owner + revisit trigger. Critical/High never.
- **Story-level risk routing** (`rules/risk-classification.md`): low-risk stories take the reduced
  chain; sensitive surfaces override the tier; gates and code review untouched.
- **Batchable stories + story groups + dispatch sizing** (`rules/mandatory-workflow.md` §1f /
  Phase 2, `agents/story-planner.md`): ≤3 mechanical stories per shared dispatch (one commit each);
  story groups defined; one story per dispatch as the default; land one end-to-end slice early.
- **Story-group fan-out** (`skills/sdlc/SKILL.md`): one orchestrator per disjoint story group in
  its own worktree; human approval per mainline merge; run-level gates on the merged output.
- **Tier probe before fan-out** (`rules/model-tiers.md`): probe-spawn each planned tier once per
  run; instant zero-token death = unavailable → fall back one tier and record.
- **Question batching** (`rules/human-in-the-loop.md`): non-blocking asks queue to CONTINUITY and
  surface as one round per gate; blocking stops and 1b interviews unchanged.
- **Spec evidence hygiene** (`agents/spec-doc-writer.md`, `rules/documentation.md`,
  `skills/spec-driven-development`): executed evidence is cited by path, never pasted into specs.
- **Warm shared test services** (`rules/testing.md`): start once per run, reuse across defect-loop
  cycles; per-test state reset and the clean-cold-start delivery check stand.
- **Operator playbook** (`docs/pipeline-speed-playbook.md`, repo-only): the same levers as
  paste-ready dispatch instructions for in-flight runs on older installs.

### Changed
- `agents/orchestrator.md`: developer dispatch input is now the story (was: whole spec) — fixing
  an internal inconsistency with [4v]'s per-story scope check; scribe persists without re-analysis;
  Stage SP carries the risk/batchable tags. Net size ~flat (854 → ≤859 lines) by design (F-036).
- `skills/_references/orchestration-patterns.md`: depth-≤1 anti-pattern now names the sdlc
  pipeline's main-session → orchestrator(s) → workers topology as the deliberate exception.

### Not adopted (deliberately)
- **Enabling specific models on a provider deployment / credential refresh commands** — user
  environment, not payload; generalized instead into the tier probe.
- **Lowering the coverage floor (100% → 97%)** — the kit already ships 90% "or as defined by the
  project's coverage policy"; the 100% floor was that project's own spec.
- **Docker-specific warm-stack guidance** — core stays container-agnostic; adopted only as
  stack-agnostic warm-services prose.
- **Giving read-only reviewers Write access so reports bypass the orchestrator** — write
  confinement and read-only review are deliberate (least-privilege, authorship bias); bounded
  handoffs fix the cost instead.
- **Orchestrator-spawning-orchestrator trees** — fan-out stays in the main session (the `sdlc`
  entrypoint); depth beyond the pipeline contract remains an anti-pattern.
- **Project-specific story merges / scope cuts (S24+S25, Phase 0b/0c)** — the general forms
  (batching, slice-early sequencing) are adopted; the specific calls stay with the projects.
```

- [ ] **Step 2:** Apply the five version edits; run `.venv/bin/python scripts/check_docs_consistency.py` → exit 0.
- [ ] **Step 3: Commit** — `git add pyproject.toml .claude-plugin/plugin.json .claude-plugin/marketplace.json src/claude_kit/__init__.py SECURITY.md CHANGELOG.md` → commit `"release: 0.82.0 — the orchestrator's context is the scarce resource"`.

---

### Task 9: full verification (all must pass — fix-forward, never skip)

- [ ] `df -h .` → ≥ 1 Gi free.
- [ ] `.venv/bin/pytest -q` → all pass (baseline on this branch's parent, main @ 0.80.0, is 1271 passed; 0 failures — prose-only change should not move the count).
- [ ] `.venv/bin/ruff check src scripts tests && .venv/bin/ruff format --check src scripts tests`
- [ ] `.venv/bin/mypy`
- [ ] `shellcheck -S warning hooks/scripts/*.sh scripts/*.sh`
- [ ] `.venv/bin/python scripts/gen_hooks.py --check`
- [ ] `.venv/bin/python scripts/check_docs_consistency.py`
- [ ] `.venv/bin/python scripts/check_cross_references.py --strict`
- [ ] `.venv/bin/python scripts/check_skill_descriptions.py --strict`
- [ ] `.venv/bin/python scripts/check_rule_sizes.py`
- [ ] Stack-leakage guard: `grep -rInE 'fastapi|sqlalchemy|alembic|docker' rules agents skills` — no NEW hits vs main (`git diff main --unified=0 | grep -iE '^\+.*(fastapi|sqlalchemy|alembic|docker)'` → empty).
- [ ] Build: `.venv/bin/python -m build && .venv/bin/twine check dist/*` (remember: local twine version quirks — reproduce on clean main before blaming the change).
- [ ] Wheel content: `unzip -l dist/claude_code_kit-0.82.0-py3-none-any.whl | grep -E 'pipeline-speed-playbook|quality-gates|sdlc'` → playbook ABSENT, edited payload files PRESENT.
- [ ] Smoke: `.venv/bin/claude-kit init /tmp/ckit-smoke82 --defaults && .venv/bin/claude-kit validate /tmp/ckit-smoke82` → both exit 0; `grep -l 'Story-group fan-out' /tmp/ckit-smoke82/.claude/skills/sdlc/SKILL.md` → present.
- [ ] Commit any fixes; re-run the failed checker after each fix.

### Task 10: push + PR (merge stays user-gated)

- [ ] `git push -u origin feat/pipeline-speed`
- [ ] PR via `gh pr create --base main --title "release: 0.82.0 — pipeline speed (12 field-verified levers + operator playbook)" --body-file /tmp/ckit-pr82-body.md` (body: summary, the 12 levers table, Not-adopted block, verification evidence, note "merge #107 first, then this — rebase handled").
- [ ] Report PR URL; remind: merging + PyPI publish are user-gated; after #107 merges, rebase this branch (version files keep 0.82.0, CHANGELOG keeps both entries).
