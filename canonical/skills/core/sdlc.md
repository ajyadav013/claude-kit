---
schema_version: 1
id: sdlc
description: Run the autonomous SDLC pipeline on a task — the single entrypoint driving spec → review → build → test → security → delivery through the profile's quality gates. Use to run the SDLC or ship a feature.
invocation: implicit
capabilities:
- filesystem.read
- delegation
request_input:
  mode: required
  hint: <feature or task description>
pause_for_human: []
references:
- artifact://project-instructions
- artifact://skill-library
- rule://continuity
- rule://mandatory-workflow
- rule://model-tiers
- rule://quality-gates
- rule://rarv-cycle
- rule://risk-classification
- rule://wave-orchestration
- state://agent-memory
- state://continuity
- state://init-options
- state://pipeline-snapshot
- state://stack-catalog
- state://ticket-board
---

# Autonomous SDLC

You are the **entrypoint** to {{kit:cli}}'s autonomous software development lifecycle. The request to
handle is:

> {{request}}

Your job is to **delegate to the `orchestrator` agent** and let it drive the pipeline — you do not
implement the work yourself here. The orchestrator never writes code; it classifies the work,
sequences the phases, spawns the specialist agents, and enforces the gates.

## 1. Load the contract

Before doing anything, read:

- `{{ref:artifact://project-instructions}}` — the project's rules and the exact build/test/lint commands.
- `rule://mandatory-workflow` — the full phase pipeline and the defect loop.
- `rule://quality-gates` — ordinary PASS requires zero Critical/High/Medium; Medium can
  only use the distinct structured accepted-risk resolution; plus blind review/Devil's Advocate.
- `rule://rarv-cycle` — the Reason → Act → Reflect → Verify self-check every agent runs.
- `rule://wave-orchestration` — the program-mode contract (audit manifest, risk-ordered
  waves, disjoint boundaries, inventory approval) — required whenever the work classifies as
  program-scale.

Then read `state://continuity` (the `load-continuity` SessionStart hook has already printed it into
context). **Detect an in-progress run:** if **Current Phase** is not idle and **Active Tasks** names a
run matching `{{request}}`, an earlier pipeline is in flight. Prefer the **schema-v2 structured
snapshot** at `state://pipeline-snapshot`: run `{{kit:cli}} pipeline resume` and use its
ordered ledger/status as the precise resume index (schema in `rule://continuity`). The
freeform CONTINUITY state is context, not authority to forge a missing/invalid ledger. Tell the user
the last resolved gate, its resolution type, and the active lane(s), then ask whether to:

- **RESUME** — re-enter at the first unresolved gate, re-running only unresolved or defect-affected
  lanes; or
- **RESTART** — abort the active run explicitly, then create a fresh run from its first gate.

If **Current Phase** is idle (or CONTINUITY was freshly seeded), proceed as a fresh run.

## 2. Discover the active profile (this decides which gates run)

Read `state://stack-catalog`. Its `gates:` and `agents:` lists are the
**authoritative set** of what the installed profile activated. Also read
`state://init-options` for the stack `selection` (frontend / backend / database) so you
point each lane at the right overlay rule.

- If either authoritative file is absent or unreadable, stop and require a supported
  `{{kit:cli}}` CLI install/upgrade. Do not guess a profile, gate set, or stack selection.

Run **only** the gates present in the snapshot's `gates:` list. The three profiles resolve to:

| Profile | Gates that run |
|---|---|
| **lean** | code-review · build-green |
| **standard** | spec-complete · em-approved · code-review · build-green · contract-clear · test-coverage · security-clear |
| **enterprise** | standard + pipeline-green · observability-ready · acceptance |

Never run a gate (or spawn its agent) that isn't in the active set — that's what makes lean fast and
enterprise thorough. Conversely, never skip a gate that *is* in the set.

## 3. Drive the pipeline

### Managed execution path (Preview, Modes A–D)

Classify the request far enough to select Mode A, B, C, or D before creating the run. If the mode is
ambiguous, stop and ask; do not let a shell command infer it from untrusted prose. Start a fresh
ledger with `{{kit:cli}} pipeline start --task '<reviewed task>' --mode <A|B|C|D>`, or use the
validated active ledger when resuming.

Before the first managed invocation, commit the selected provider's scaffolded instructions and
all application inputs. The integration worktree is created from `HEAD`; only mutable `.ckit/`
state is exempt. If provider configuration or application changes are uncommitted, stop and ask the
human to commit or stash them rather than launching a worker with incomplete context.

When `CKIT_EXPERIMENTAL=1` is already an explicit operating choice, prefer the managed executor:

```text
{{kit:cli}} pipeline run --provider {{host:lower}} \
  --condition ui-surface-present=<true|false> \
  --condition frontend-surface-present=<true|false> \
  --condition backend-surface-present=<true|false> \
  --condition api-contract-surface-present=<true|false> \
  --condition api-surface-present=<true|false> \
  --condition risk-or-uncertainty-present=<true|false> \
  --condition multiple-boundaries-present=<true|false> \
  --condition end-to-end-path-present=<true|false> \
  --condition application-attack-surface-present=<true|false> \
  --condition deploy-surface-present=<true|false> \
  --condition observable-surface-present=<true|false>
```

Decide every value from the reviewed task and installed stack; never guess an unknown surface. The
first invocation freezes the applicable decisions, complete workflow digest, mode-specific gates,
gate owners, and stage history in the single shared ledger. Later invocations may omit the condition
arguments, including after switching providers.

The managed executor is the sole dispatcher for that invocation — do not also spawn an orchestrator.
On `waiting-gate`, inspect the run-owned stage artifact, record exact findings, resolve only the named
gate through the structured lifecycle, and invoke `pipeline run` again. On `human-stop` (exit 3),
stop for the requested action. Its persistent run-owned worktree is not merged automatically; present
its path/diff for an explicit human-controlled merge after success.

Managed approval resumption is not implemented: a generic local file plus a claimed identity is not
a trustworthy stage/attempt/workspace-scoped, one-shot authorization. `approved` resolutions remain
pending and fail closed. A human may record `rejected` only to trigger re-planning or abort; it never
authorizes the stopped action. Use the legacy/manual lifecycle only with an explicit acknowledgement
that its approval record is not a managed-execution capability grant.

The built-in subprocess backend does not attest `process.descendant_containment`: portable process-
group cleanup cannot contain a deliberately re-sessioned descendant. Every selected semantic shell
role therefore returns an `unsupported-required-capability` human stop before spawn. A provider
adapter may waive that requirement only for a passive read-only, nondelegating role on an exact
compatibility-pinned host after a fail-closed probe disables every command, extension, and
delegation surface; the coordinator must supply a bounded, filtered projection of tracked text.
All other roles still require containment. Consult the installed runtime support matrix. Do not
retry, resolve, or bypass a missing-capability stop; resolving a pause does not grant the technical
boundary. Use an independently contained backend, or obtain explicit human acknowledgement before
choosing the manual orchestration path.

Mode E is not managed-executable yet because typed wave completion, restore points, and inventory
approval are not modeled. It must stop at that boundary and use the manual Mode E contract below only
with an explicit human acknowledgement of the degraded path. If `pipeline run` is unavailable or
Preview execution was not opted into, report that fact and obtain the same acknowledgement before
using manual delegation; never silently downgrade a managed run.

### Manual orchestration path

For acknowledged Mode E/manual fallback, spawn the `orchestrator` agent via the {{tool:delegate}}
tool with the task ({{request}}), active gate list, and stack selection. Instruct it to:

1. **Classify** the work — bug fix vs. feature; single-stream vs. parallel lanes (backend/frontend);
   fast-track (< 5 files) vs. full pipeline vs. **program-scale** (> ~20 files / multiple subsystems,
   or any irreversible step: production data, schema migration, deletion sweep). Fast-track collapses
   to the lean gate set regardless of profile. Program-scale work runs **Mode E — wave
   orchestration** per `rule://wave-orchestration`: parallel read-only audits → one frozen
   scope manifest (UNKNOWN = stop and ask) → risk-ordered waves with disjoint file boundaries →
   gate-runner agents between waves → inventory approval before irreversible steps → a knowledge
   closeout wave. (Where the session has {{host_feature:dynamic-workflows}}
   (≥ 2.1.154), a wave's fan-out may execute as one workflow run — the wave contract, gates, and
   human approvals are unchanged; see that rule's "Native dynamic workflows as the wave
   substrate".) Have the story planner tag each story (risk / batchable); low-risk stories inside
   a full run route through the reduced chain per `rule://risk-classification` →
   Story-level routing.
2. **Record** the plan/context in `state://continuity`, but create and mutate gate-precise state
   only through the schema-v2 lifecycle. Use `pipeline start --task ...` for fresh work or `adopt`
   with starting gate/reason/adopter for genuine pre-ledger work; use `resume` after interruption.
   Before resolving a gate, use `record-findings` with exact Critical/High/Medium/Low/Cosmetic
   counts plus a project-contained evidence report; start/adopt zeros are unrecorded placeholders.
   Record PASS with `close-gate <gate> --evidence <file>`, a catalog-authorized conditional result
   with `not-applicable <gate> --condition <id> --reason '<why>' --evidence <file>`, and each Medium
   exception with structured `accept-risk` fields. Critical/High have no waiver; accepted-risk is
   never PASS. Finish with `complete` (which persists the accepted risks in `final_summary`) or
   `abort`; a later start/adopt validates and hash-archives the terminal run automatically. Never
   hand-write `gate_history` or snapshot JSON. If the installed CLI lacks a required
   lifecycle command or a safe-path/lock write fails, report its version/error and block for repair
   or upgrade. On resume, re-enter at the first unresolved gate and never re-apply committed work.
3. **Route skills and models explicitly — and announce fan-out before spawning it.** Every agent
   the orchestrator spawns is told which skill(s) to load for its stage (the orchestrator's Skill
   Routing table; only skills actually installed under `artifact://skill-library/`) and runs on the model
   tier its work deserves (`rule://model-tiers`) — cheap for audits/scans, standard for
   build/review, top tier only for orchestration and hard reasoning. Before forking any parallel
   phase (review lanes, test lanes, security scanners, Mode E waves), it states the planned
   lane/agent count and model tiers in chat and records them in `state://continuity`, so the
   human can veto the scale before tokens are spent. Before the run's **first** fan-out, probe each
   planned model tier with one trivial spawn and fall back per `rule://model-tiers` →
   "Probe before fan-out".
4. **Run each active phase with its gate**, in order, using only the profile's agents:
   spec & dev-docs → story planning → **ticket creation + open the board** → (design, if UI) →
   senior/architect/EM review → implementation (one worktree per lane) → code review →
   unit + e2e tests → test-coverage merge → security clear → pipeline-green +
   observability-ready (enterprise) → acceptance (enterprise) → PR.
   At ticket creation the orchestrator runs `{{kit:cli}} tickets --open` **once** and reports the
   `file://` path, so the human can watch the run in a browser instead of reading chat for status.
   The `capture-ticket-telemetry` Stop hook keeps that page current for the rest of the run —
   creating the file is what switches the hook on.
5. **Enforce gates** with the `quality-gates.md` severity model and a green RARV Verify before each
   handoff. On a unanimous PASS, run the `devils-advocate` agent before the gate counts.
6. **Run the defect loop** when a gate fails: document, re-run only the affected lane(s), re-merge,
   re-test — never patch informally around the process.

If the `orchestrator` agent is unavailable in this session, act as the orchestrator yourself,
following the same steps.

### Story-group fan-out (optional, feature scale)

When the story breakdown yields **two or more immediately-startable story groups** (maximal
dependency-connected story sets with mutually disjoint file boundaries —
`rule://mandatory-workflow` §1f) and the run is not program-scale (Mode E), parallelize
across context windows instead of inside one: spawn **one orchestrator per group**, each in its
**run-owned git worktree** per `rule://continuity` → Concurrency. Worktrees contain code and
stage artifacts only: they never receive an independent continuity file, pipeline snapshot, or
gate ledger. The primary checkout's single `state://pipeline-snapshot` remains authoritative for
every group, provider, retry, and merge. Announce the scale first (N orchestrators × model tiers)
so the human can veto it. Merge in dependency order, one group at a time, with **human approval per
mainline merge** (workers propose; humans approve), then run the run-level gates — test-coverage
across groups, security-clear on the merged output — in the primary checkout and record them in
that same ledger. A group that fails escalates per the normal retry protocol; healthy groups still
merge; a failed group's stories return to the backlog — never merge a group whose gates didn't
pass.

## 4. Stop for the human where required

Pause and ask the user at the points the workflow requires: ambiguous requirements, spec
confirmation, destructive or project-wide changes, and choice of deploy/release target. In the
enterprise profile, the **acceptance** gate hands off to a human before the PR is finalized.

## 5. Close the loop

When the active gates are green: summarize what shipped, list any open issues by severity, ensure
`state://continuity` reflects the final state, and promote any durable lessons with the
`remember` skill (into `{{state_dir:state://agent-memory}}`).

Re-print the board path (`state://ticket-board`) in that summary. By the end of a long
run the link from Stage TK is far up the scroll-back, and the finished board — every ticket DONE,
with its commits, files and per-agent token cost — is the artifact worth keeping.

Begin by confirming your classification, the active profile + gate set, and the stage plan — then
proceed.
