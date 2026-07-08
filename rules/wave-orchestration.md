# Wave Orchestration (Program-Scale Work)

When a single run is too big to be one feature pipeline — a migration, a repo-wide refactor, a
deprecation sweep, anything touching many files, multiple subsystems, production data, or a schema —
the orchestrator switches from *feature mode* to **program mode**: one pure orchestrator, many
short-lived workers, work sequenced into **risk-ordered waves** behind a **frozen scope manifest**.

The failure mode this rule prevents is **context collapse**: the thing doing the work gradually
loses the plot of the overall program. The parent stays a pure planner (it writes zero code and
holds the plan, the scope rulings, and per-wave state); every worker gets a fresh, focused context
with exactly one job.

> Patterns adapted from Ryan Carson's public writeup of a 40-session orchestrated migration
> (x.com/ryancarson, Jul 2026): audit-first manifest, risk-ordered waves, disjoint file boundaries,
> gate-runner sessions, inventory approval, explicit escalation, docs-as-final-wave.

## When this rule applies

Classify the run as **program-scale** when any of these hold (when uncertain, ask the human):

- the change spans **many files across multiple subsystems** (rule of thumb: > ~20 files or > 2
  independent lanes of the normal pipeline);
- it includes an **irreversible step** — production data mutation, schema migration, deletion sweep,
  dependency prune — regardless of file count;
- it is explicitly a migration / modernization / decomposition program rather than one feature.

Feature-scale work stays on the normal pipeline in `.claude/rules/mandatory-workflow.md`. Everything
below *adds to*, and never replaces, the gates in `.claude/rules/quality-gates.md`, the risk tiers in
`.claude/rules/risk-classification.md`, and the stops in `.claude/rules/human-in-the-loop.md`.

## The seven obligations

### 1. Audit first; freeze the findings in a single manifest

Wave 0 is **parallel, read-only audit workers**, each covering one disjoint slice of the codebase
(routes, entry points, schema, shared libraries, scripts, docs, CI). Their findings are synthesized
into **one manifest file committed to the repo** (`docs/specs/{program}_manifest.md`) that assigns
**every unit of code a verdict and a wave number**.

Two properties make the manifest load-bearing:

- **No worker re-litigates scope.** Every worker prompt states: *the manifest is the source of
  truth*. Without this, each worker derives its own opinion of what is in scope — and they disagree.
- **UNKNOWN means stop and ask.** Anything the audits were silent on is explicitly marked `UNKNOWN`
  with the instruction: do not guess; get a ruling. Human rulings are recorded **into the manifest**
  so later workers inherit them. Scope changes are manifest **overrides written by the orchestrator**,
  never ad-hoc decisions by whichever worker hits the surprise.

Wave 0 also creates a **restore-point git tag** before any change lands.

### 2. Order the waves by risk, not by convenience

Sequence from safest to most irreversible; irreversible steps run **last**, and only after every
unit that depends on the affected state has verifiably been updated:

| Wave | Content | Risk |
|------|---------|------|
| 0 | audits + manifest + restore-point tag | none |
| early | changes verified to have no live dependents | near zero |
| middle | shared-infrastructure surgery, then the bulk of the changes | medium |
| late | data changes (dry-run inventory + backup first), then schema/structural migrations | high |
| final | dependency pruning + docs/knowledge closeout (§7) | low |

Use the `risk-classifier` agent / `.claude/rules/risk-classification.md` tiers to place each
manifest unit. A unit whose risk is discovered to be higher mid-flight is **demoted to a later
wave** via a manifest override — never absorbed into the current one.

### 3. Disjoint file boundaries make parallelism safe

Within a wave, workers run in parallel **only** when their file boundaries are explicitly stated and
**mutually disjoint**. Every parallel worker prompt names the exact files/directories it may touch;
no two concurrent prompts overlap; a file not in any boundary is out of scope for everyone. This is
ordinary task decomposition — but workers need it **stated in the prompt, every time**. A worker that
needs a file outside its boundary stops and reports (§6); it does not edit it.

### 4. Gate every wave; gates are their own workers

No wave starts until the previous one passes a gate, and gates are run by **dedicated gate-runner
workers** (fresh context, no authorship bias — the severity model of
`.claude/rules/quality-gates.md` applies):

- a real **regression suite** (the project's test runner / e2e suite) after every code wave, on an
  isolated branch/worktree — never on the live mainline;
- before any destructive or data-touching wave: a **backup audit** (verify backups exist, are
  recent, and are restorable) plus a fresh snapshot/restore point;
- a **git tag** marking the restore point for every wave that lands changes.

A failed gate produces a **scoped fix worker** for exactly the failing surface, then the gate
re-runs. That is the system working: the gate turns a would-be shipped defect into a same-wave fix.

### 5. Workers propose; humans approve (the inventory pattern)

Irreversible steps follow `.claude/rules/human-in-the-loop.md`, with this sharpening: the worker
produces a **precise inventory** of what it will touch (the exact rows/files/keys and counts — via
dry-run where possible), the human approves **that inventory**, and the worker then executes
**exactly the approved inventory** and re-verifies the counts afterwards. Approve the list, not the
idea. Merges to the mainline, data changes, schema migrations, and `UNKNOWN` rulings are always
human decisions; everything else is the orchestrator's.

### 6. Define the escalation path before the surprises arrive

Every worker prompt states what to do when reality disagrees with the manifest: **stop, report to
the orchestrator, don't improvise.** The orchestrator absorbs the surprise into the plan — demote
the unit to a later wave, record a manifest override, or escalate to the human — and workers never
make scope decisions. (Failure handling for crashed/looping workers stays as in
`.claude/rules/agent-resilience.md`; this section is about *scope* surprises, not tool errors.)

### 7. Leave the campsite cleaner: the knowledge wave

The final wave updates the project's agent-facing knowledge to describe the **new** state of the
world: `CLAUDE.md`, affected `.claude/rules/` prose, skills, runbooks, and durable lessons into
agent memory (`remember` / `consolidate-learnings`). If your engineering is agent-driven, your
documentation is load-bearing infrastructure — stale instructions poison every future session. This
wave is part of the program, not an afterthought.

## Cost discipline

Match each worker's model to its task per `.claude/rules/model-tiers.md`: audits and mechanical
sweeps run on the cheap tier; entanglement surgery and gate adjudication on the standard tier; only
the orchestrator and genuinely hard reasoning on the top tier. The audit wave is the cheapest
insurance in the program — never skip it to save its cost.

Announce the spend before it happens: the manifest states the worker count per wave, and the
orchestrator repeats that count (and its model tiers) when opening each wave — scale is vetoable
before the tokens go out, not after.

## Native dynamic workflows as the wave substrate

Claude Code ≥ 2.1.154 ships a native **dynamic-workflows engine**: Claude writes a JavaScript
orchestration script and a background runtime executes it — dozens to hundreds of subagents per
run, intermediate results held in script variables instead of anyone's context, per-agent progress
and token spend in `/workflows`, and in-session resume (completed agents return cached results).
That engine and this rule solve different problems, and they compose:

- **This rule is the contract; the engine is a substrate.** The manifest, risk-ordered waves,
  gate-runner verdicts, and human approvals are not replaced by the engine — it provides execution
  capacity, not governance.
- **One workflow run per wave.** The runtime accepts **no mid-run user input**; its own docs'
  advice for sign-off between stages is to run each stage as its own workflow. That maps exactly
  onto this rule: a wave's worker fan-out may run as one workflow run (Wave 0's parallel read-only
  audits are the canonical fit; so is a bulk middle wave over disjoint boundaries), and everything
  human — gate-verdict review, inventory approval (§5), `UNKNOWN` rulings — happens **between
  runs**, in the conversation. Never place an irreversible step inside a run: nothing can pause
  the runtime to ask.
- **The committed artifacts stay the durable record.** Resume is session-scoped (a run does not
  survive exiting the session), so the manifest, wave state, and restore-point tags — not the run —
  remain the source of truth, exactly as this rule already requires.

Availability is not guaranteed: the engine needs a paid plan (opt-in on Pro via `/config`), and
users or orgs can disable it (`"disableWorkflows"`, `CLAUDE_CODE_DISABLE_WORKFLOWS=1`, managed
settings). Plan the program under this rule first; pick the substrate per wave — ordinary parallel
subagents or a workflow run — based on what the session actually has.

## Relationship to other rules

- **`.claude/rules/mandatory-workflow.md`** — the feature pipeline each worker still follows *inside*
  its unit of work; this rule sequences units into waves above it.
- **`.claude/rules/quality-gates.md`** — the severity model every wave gate applies.
- **`.claude/rules/risk-classification.md`** — the tiers that order the waves.
- **`.claude/rules/human-in-the-loop.md`** — the stop points; §5 here is its inventory sharpening.
- **`.claude/rules/agent-resilience.md`** — worker crash/retry handling.
- **`.claude/rules/model-tiers.md`** — per-worker model selection.
- **`.claude/rules/continuity.md`** — the manifest complements, never replaces, CONTINUITY.md and
  the pipeline snapshot; wave state lives in both.
