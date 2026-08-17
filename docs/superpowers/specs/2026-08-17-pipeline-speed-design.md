# Pipeline Speed — Design (0.82.0)

**Date:** 2026-08-17 · **Status:** approved by user (sections 1–5) · **Target:** one release
(0.82.0) + an operator playbook for in-flight runs.

## Context

claude-kit's SDLC pipeline ran live in three user projects. All three were slow. Three
independent field-feedback sets (one per project, 18 levers total) diagnosed why. This design
triages those levers — plus our own analysis — into kit payload changes, with every "the kit
lacks X" claim adversarially verified against the payload by 12 independent checkers
(single-word wrap-safe greps + full-file reads; 11 of 12 initial gap-claims were partly wrong).

**Unifying principle:** the orchestrator's context window is the pipeline's scarce resource.
Run throughput = stories-per-window × concurrent-windows. Every adopted lever either spends
less context per story (bounded handoffs, mechanical VALIDATE, spec hygiene) or buys more
windows (story-group fan-out, one-story dispatches) or removes waste that burns wall-clock
without buying rigor (ceremony on low-risk stories, unbounded review rounds, cold infra,
mid-lane interruptions, unprobed fan-outs).

**Meta-constraint:** `agents/orchestrator.md` (854 lines) is the agent with an open
oversized-agent finding (F-036 lead: it spawns 1/8 while the ~100-line security-reviewer hits
6/8). This change lands **net-zero growth** on that file. Every edit goes to the smaller
rule/agent/skill that owns the concern; orchestrator.md gets only one-clause pointers and one
correction.

## Decisions taken (user-confirmed)

1. **Deliverable:** kit release 0.82.0 **and** an operator playbook for the three in-flight
   runs (repo docs, not wheel payload).
2. **Rigor posture:** per-story risk tiering and the review-round total budget are **default
   behavior**, not opt-in. Gate semantics (zero Critical/High/Medium) unchanged everywhere.
3. **Approach:** all 12 levers in one release. Every edit is a small bounded prose change to
   an existing file; no new rules, agents, hooks, or catalog entries — minimal drift-guard
   blast radius; the release ceremony is paid once.

## Not adopted (deliberately) — for the CHANGELOG block

| Field lever | Why not |
|---|---|
| Enable claude-sonnet on the Vertex deployment; refresh gcloud ADC | User environment, not payload. Generalized residue adopted as the Stage-0 tier probe (§4). |
| Drop the 100% coverage floor to ~97% | The kit already sets 90% "or as defined by the project's coverage policy" (`rules/testing.md:22`). The 100% floor was that project's own spec. |
| Merge specific serial stories (S24/S25); cut Phase 0b/0c scope | Project story-design decisions. General forms adopted: vertical-slice-early + batchable stories. |
| Keep the Docker stack warm | Docker is banned from the agnostic core. Adopted only in stack-agnostic form (§4, warm shared test services). |
| Give read-only reviewers Write access so reports skip the orchestrator | Rejected: write confinement and read-only reviewers are deliberate (authorship-bias + least-privilege). Bounded handoffs (§1) fix the cost instead. |
| Orchestrator-tree topologies (orchestrators spawning orchestrators) | Rejected: fan-out belongs to the main session (the `sdlc` skill), which already spawns the orchestrator. Depth stays main session → orchestrator(s) → workers. |

## Section 1 — Spend less context per story (levers: bounded-handoffs, validate-mechanical-bound, spec-evidence-hygiene)

Verified state: handoff *shape* (verdict + severity counts + findings table) is already
mandated across scanners and reviewers; handoff *size* is bounded nowhere, and the scribe
pattern makes full report bodies transit orchestrator context. [4v] VALIDATE already names the
right mechanical checks but has no lower bound — nothing forbids the orchestrator re-deriving
the reviewer's work (the field runs' md5 mutation proofs). Spec files have no hygiene norm
(CONTINUITY has a size budget; specs don't — one field project's specs hit 7,279 lines and
every agent read them).

Edits:

1. **`rules/quality-gates.md` §2.5 — "Bounded handoff" block.** Every reviewer/tester/scanner
   handoff leads with the header the orchestrator actually reads: verdict line, severity
   counts, findings table (`file:line`), evidence citations (captured command + exit line, or
   a `.claude/state/` evidence-file path). The full report body follows below a marker; the
   orchestrator persists it verbatim to its canonical path and **must not re-analyze it**.
   Explicit reconciliation: evidence cited by persisted+hashed path satisfies "the proof
   travels with the handoff" — this bounds *what the orchestrator reasons over*, it does not
   weaken §2.5.
2. **`rules/quality-gates.md` §2.5 — "VALIDATE is mechanical" block.** The orchestrator's
   independent VALIDATE is: suite/lint/build **exit codes** it re-ran itself + `git diff
   --name-only` compared to the declared story scope + **recording** the coverage number the
   suite already prints (recording, not a second coverage gate). Nothing more. Diff-level
   correctness belongs to the Code Reviewer; re-deriving it is a routing error, not extra
   rigor. Wording must not read as license to skip the independent re-run itself.
3. **`agents/orchestrator.md`** — [4v-FE] gains one clause ("…and nothing more: correctness
   review is [4b]'s job"); the line-12 scribe sentence gains "without re-analysis". [4v-BE]
   inherits via "same contract". Net ≤ +2 lines.
4. **Spec evidence hygiene** — one rule/checklist line each in `agents/spec-doc-writer.md`,
   `rules/documentation.md` §8, and `skills/spec-driven-development/SKILL.md` ("Keeping the
   Spec Alive"): the spec holds requirements and decisions; executed evidence (command output,
   measurement blocks) lives at its `.claude/state/` or artifact path — cite the path, never
   paste the output. Carve-outs stay legal: §8's one-line changelog notes; requirement/decision
   updates. Binding on every agent that edits specs (spec-doc-writer, senior devs,
   documentation flows), not just the write-confined orchestrator.

## Section 2 — Buy more context windows (levers: story-lane-orchestrators, checkpoint-dispatch-granularity)

Verified state: Mode C parallelizes only whole *features*, inside one orchestrator context.
`rules/continuity.md` §Concurrency already sanctions concurrent pipelines on one repo via
per-run worktrees (isolation substrate exists); the story-planner already emits disjoint
immediately-startable groups (the fan-out input exists). Missing: the trigger, the topology
permission, and the merge protocol. Also `agents/orchestrator.md:383` is internally
inconsistent: Fork Point 2 hands the developer "Approved spec + design spec" while [4v]
validates against "the story's declared file scope" (singular).

Edits:

1. **`skills/sdlc/SKILL.md` — story-group fan-out sub-step (step 3).** After the story
   breakdown passes its coverage gate (and the run is not Mode E), if the graph contains ≥2
   disjoint, immediately-startable story groups with mutually disjoint file boundaries, the
   entrypoint (main session) MAY spawn **one orchestrator per group**, each working in its own
   git worktree per `continuity.md` §Concurrency with its own CONTINUITY/snapshot/ledger
   seeded there. Announce the fan-out scale (N orchestrators × model tiers) before spawning.
   Merge back **in dependency order, one group at a time, with human approval per mainline
   merge** (orchestrator Rule 22 / wave-orchestration §5 preserved). Run-level gates
   (test-coverage merge across groups, security-clear on the merged output) run in the primary
   checkout after merges. Ledger ownership: each group's ledger is authoritative for its own
   per-story gates; the primary checkout's ledger records the run-level gates.
2. **`rules/mandatory-workflow.md` §1f** — one-sentence definition: a **story group** is a
   maximal dependency-connected set of stories whose combined file boundary is disjoint from
   every other group's; groups are the unit of orchestrator fan-out.
3. **`rules/continuity.md` §Concurrency** — one cross-reference sentence (story-group fan-out
   is the sanctioned use of concurrent pipelines).
4. **`skills/_references/orchestration-patterns.md`** — one clarifying sentence resolving the
   "depth ≤ 1" anti-pattern tension: the sdlc pipeline's sanctioned topology is main session →
   orchestrator(s) → workers; the depth advice governs ad-hoc orchestration outside the
   pipeline contract.
5. **Dispatch sizing** — `rules/mandatory-workflow.md` Phase 2 intro: *prefer one story per
   implementation dispatch* — a crash then loses at most one story of un-persisted work;
   CONTINUITY + snapshot at stage transitions is what makes resume cheap. Phrased as a default
   calibrated to story size (the sprint skill's "don't hardcode a magic count" stands; Mode
   D/proportionality unaffected). `agents/story-planner.md` gains "each story is the unit of
   one dispatch". **`agents/orchestrator.md:383` corrected**: developer Input becomes the
   story under implementation (+ spec/design refs) — a fix, not growth.

## Section 3 — Less ceremony where risk is low (levers: story-batching, per-story-risk-tiering, review-round-total-budget, vertical-slice-early)

Verified state: implementation/review ceremony is already per-lane (not per-story — the field
runs' per-story ceremony was their orchestrators' unforced choice; §1's VALIDATE bound and
§2's dispatch sizing now make the intended shape explicit). Fast-track exists per-run only.
Per-reviewer retry caps exist; no cross-chain total. The waiver machinery **already ships**
(`claude-kit pipeline close-gate --force --override-reason` → audited `gate_overrides`,
surfaced by `validate`) but no prose tells the human it exists or what accepting a residual
Medium requires. Vertical slices are preferred but early-slice *sequencing* is stated nowhere.

Edits:

1. **`agents/story-planner.md`** — story output fields gain a **risk tag** (`low` |
   `standard`; when in doubt, standard — and the orchestrator may consult `risk-classifier`)
   and a **`batchable` tag** for mechanical low-risk stories (docs, changelog, packaging,
   examples, version bumps). Sequencing gains: land **one end-to-end vertical slice early**,
   so every later story validates against a running system instead of prose (reconciled with
   planning-and-task-breakdown's "foundation-first" phrasing — the slice IS the foundation).
   Constraint stays advisory: NOT a new §1f gate criterion.
2. **`rules/risk-classification.md` — "Story-level routing" subsection.** Inside a full run, a
   `low`-risk story routes through the reduced chain (developer → code reviewer → tester);
   `standard` keeps the full chain. Run-level gates and zero-C/H/M semantics unchanged — the
   tier governs **which agents spawn per story, never what passes**. The specialist-routing
   table (`mandatory-workflow.md`: security/observability surfaces trigger on surface touched,
   never size) **overrides** the tier. Explicit reconciliation with the "tier sets the minimum
   bar — never lower it" ratchet: the ratchet governs caution and gate semantics; this section
   allocates ceremony.
3. **Batching** — `rules/mandatory-workflow.md` §1f/1g: up to 3 `batchable` stories sharing a
   disjoint combined boundary may share one developer dispatch and one review pass, **one
   commit per story**, same stages — never stage-skipping. Ticket per story still opens
   (Stage TK unchanged).
4. **`skills/sdlc/SKILL.md` step 1** — classification also instructs per-story tiering at
   breakdown. **`agents/orchestrator.md`** Stage SP gets a ≤2-line routing hook.
5. **Review-round total budget** — `rules/quality-gates.md` §2 (the self-declared "restated in
   one place" home for budgets): the whole spec review chain (1c–1e.5) gets **2 full re-review
   generations**; when a third would start, escalate to the human with the unresolved findings
   and the **named waiver path**: `claude-kit pipeline close-gate --force --override-reason
   '<finding>: accepted as known gap — owner: <role>, revisit: <trigger>'`. Owner + revisit
   trigger mirror the CONFIRMED-WITH-COSTS cost record; they live in the free-text reason —
   **no `pipeline.py` schema change**. A waiver is an audited override (status `overridden`,
   WARNed by `validate`), never a PASS re-definition. Criticals/Highs are never waived this
   way. `rules/human-in-the-loop.md` exhausted-budgets row names both outcomes (fix vs
   audited waiver).

## Section 4 — Run reliability (levers: stage0-capability-preflight, question-batching, warm-test-infra)

Verified state: roster/profile/ledger probes exist at Stage 0; a model-tier availability probe
and credential-freshness check do not (field runs: 34/38 agents pin an unavailable tier →
0-token instant spawn failures; 3 crashes in 24h burning 45–90 min each). Question
aggregation exists at the spec boundary; nothing tells mid-lane agents to queue non-blocking
questions. Warm-infra reuse exists only in the pytest collection skill, not the agnostic core.

Edits:

1. **`rules/model-tiers.md` — "Probe before fan-out" subsection.** Before a run's first
   fan-out, probe-spawn one trivial agent per planned tier. An instant / zero-token failure
   means the tier is unavailable on this deployment: fall back one tier, record the override
   in CONTINUITY, and keep it for the rest of the run. Credential freshness is verified by the
   probe's *behavior* — never by reading secrets/.env (guardrails-compatible). Deployment-
   neutral wording (no Vertex/Bedrock/model-ID specifics). `skills/sdlc/SKILL.md` step 3:
   "announce **and probe**" one-liner. `rules/agent-resilience.md`: one fallback-table row.
2. **`rules/human-in-the-loop.md` — blocking vs non-blocking asks.** Blocking questions stop
   now (existing table unchanged — destructive approvals, guardrail trips, gate decisions stay
   synchronous). Non-blocking questions are **queued** to CONTINUITY's Open Questions and
   surfaced as **one batch at the next gate/join**. Explicit carve-out: 1b intent-extraction
   interviews stay one-question-at-a-time (`interview-me` design stands).
3. **`rules/testing.md` — warm shared test services subsection** (near Parallel Execution):
   start the suite's shared services/dependencies once per run and reuse them across
   iterations and defect-loop cycles, paired with per-test state reset (rules 7–8 still bind);
   explicitly does **not** waive Pipeline Green's clean cold-start verification. Tool-agnostic
   wording; cross-reference `testing-conventions` as a concrete instance.

## Section 5 — Operator playbook + release mechanics

**`docs/pipeline-speed-playbook.md`** (repo docs; NOT bundled into the wheel): paste-ready
run-level instructions for in-flight installs (0.79–0.81), one numbered recipe per lever:

1. Tier probe + explicit `model:` override on every dispatch (with the 0-token failure
   signature to watch for).
2. One story per dispatch; resume from `.claude/state/pipeline-snapshot.json`, never re-run
   passed gates.
3. The waiver command path — gated on `claude-kit --version` (older CLIs lack `--force`;
   hand-write the `gate_overrides` entry per `continuity.md` schema if so).
4. Manual story-group fan-out recipe (what to tell the entrypoint; worktree + merge-order +
   human-merge-approval steps).
5. Paste-into-prompt lines bounding VALIDATE and requiring the bounded handoff header.
6. Spec surgery: move executed-evidence blocks to `.claude/state/gate-evidence/`, leave
   citations (the 7,279-line-spec fix); plus batch-your-questions and warm-infra one-liners.

**Release mechanics:**

- **Branch:** `feat/pipeline-speed` off main. **Merge PR #107 (0.81.0) first**, then rebase —
  avoids the 5-file version-bump conflict and honours the no-stacked-PR rule.
- **Version:** 0.82.0 in all five places + CHANGELOG entry including the Not-adopted table
  above.
- **Checks (all must stay green):** pytest; ruff check+format; mypy; shellcheck; `gen_hooks.py
  --check` (untouched — no hook changes); `check_docs_consistency.py`;
  `check_cross_references.py --strict` (new cross-refs: quality-gates ↔ orchestrator [4v],
  risk-classification ↔ mandatory-workflow, model-tiers ↔ sdlc skill, continuity ↔ sdlc
  skill); `check_skill_descriptions.py --strict` (sdlc description unchanged); rule-size
  check (quality-gates.md grows ~25 lines — verify against the cap); stack-leakage grep (the
  testing.md warm-infra wording must stay container-term-free).
- **Tests:** no payload file is added or removed (file-count/manifest tests stable). Check for
  content-pinned tests on edited prose (`grep -rn` the edited phrases under `tests/`) — the
  repo pins deliberate decisions as tests; any failing pin is examined against its recorded
  rationale, never silenced.

## Error handling / failure modes

- **A fan-out group fails** → its orchestrator escalates per existing retry protocol; other
  groups are unaffected (lane-isolation rule already covers this); the main session merges
  completed groups and reports the failed one — never merges a group whose gates didn't pass.
- **Tier probe itself fails for all tiers** → the run stops before any fan-out with a clear
  capability report (better than the field failure mode: mid-run 0-token deaths).
- **Waiver misuse risk** (rubber-stamping Mediums) → bounded: `validate`/`status` WARN on
  every override; owner + revisit trigger required in the reason; Critical/High never
  waivable; the budget only *escalates to a human* — it never auto-waives.
- **Batch hides a risky story** → the specialist-routing override (surface-touched, never
  size) still fires per story; `batchable` misuse is caught at review (one commit per story
  keeps diffs attributable).

## Testing strategy

Prose-only payload change → the deterministic gates above are the test surface, plus:
`claude-kit init /tmp/ckit-smoke82 --defaults` smoke (scaffold intact), `claude-kit validate`
on the smoke install, and a wheel-content spot check (`unzip -l`) confirming the playbook doc
is NOT bundled while edited payload files are.

> Risk acceptance (LLM-guardrails hook, 2026-08-17, session owner): this change is
> prose-only pipeline guidance — it adds no new model I/O surface, ingests no new untrusted
> input, and renders no model output; OWASP-LLM screening N/A. Review at next payload change
> that adds a real model boundary.
