# Goal Setting & Monitoring

**If you can't say what "done" looks like and measure whether you're getting there, you're drifting.**

An agent that can't say *what done looks like* and *whether it's getting there* drifts. Every task
runs against **measurable success criteria** that are recorded up front, **monitored** as work
proceeds, and used to **prioritize** what to do next. This rule turns "I produced output" into "I met
a defined, checkable goal" — and decides what to work on first.

> Adapted from *Agentic Design Patterns* (A. Gulli), Ch. 11 "Goal Setting and Monitoring" and Ch. 20
> "Prioritization." Concepts paraphrased for this kit.

The feature spec already *defines* acceptance criteria (`spec-doc-writer`, `.claude/rules/mandatory-workflow.md`
stage 1c) and `acceptance-reviewer` checks delivery against them. This rule makes those criteria
**measurable + actively monitored + prioritized** across the run, including for bug fixes and
fast-track work that never produce a full spec.

## 1. Set measurable success criteria

Before doing the work, state the goal so success is **verifiable, not vibes**. A good criterion is:

- **Specific** — names the observable behavior/output, not a feeling ("returns 404 with an error body
  for a missing id," not "handles errors well").
- **Measurable** — has a check that can pass or fail (a test, a command exit code, a metric threshold,
  a reviewable artifact).
- **Bounded** — clear scope and out-of-scope; what is explicitly *not* being done.

Record them in `.claude/CONTINUITY.md` (and for features, they live in the spec). If you cannot make a
criterion measurable, that ambiguity is a human decision point — see
`.claude/rules/human-in-the-loop.md`.

**Self-check:** is every criterion something a command, test, or metric can pass or fail? If it's a
feeling ("make it better"), it isn't a criterion yet — sharpen it or escalate it.

## 2. Monitor progress against them

- **Track, don't assume.** As stages complete, check actual results against the criteria — the RARV
  **Verify** step (`.claude/rules/rarv-cycle.md`) is where each criterion gets proven.
- **Watch the process signals** in `.claude/rules/quality-gates.md` (gate first-pass rate, fix
  iterations, defect-loop cycles). A degrading trend is an early warning, not a gate.
- **Detect drift.** If work is diverging from the criteria, the criteria turned out wrong, or scope is
  creeping, **stop and correct** — revise the plan, re-scope with the human, or escalate. Don't push a
  growing diff toward a goal that no longer fits.

## 3. Prioritize what to do next

When multiple tasks/stories/findings compete, rank by:

| Criterion | Ask |
|-----------|-----|
| **Urgency** | Is something blocked, broken, or time-sensitive right now? |
| **Importance** | How much does this move the actual goal / success criteria? |
| **Dependencies** | Does other work require this first? Do the unblockers before the blocked. |
| **Risk** | Tackle the riskiest/most-uncertain piece early, while there's room to change course. |

**Dynamic re-prioritization:** re-rank as conditions change — a new blocker, a failed gate, a human
answer that reshapes scope. The order chosen at the start is a hypothesis, not a contract. The
`story-planner` orders parallelizable stories up front; this rule keeps that order honest as the run
proceeds (and the `planning-and-task-breakdown`, `triage`, and `sprint` skills apply the same criteria
at backlog/sprint scope).

## 4. Instrument the run so monitoring is measured, not guessed

§2 says *track, don't assume*. The cheapest way to track an agent honestly is to **emit telemetry from
the run itself** instead of reconstructing it after the fact. Model the run as a **span tree** —
`session → turn → tool call / model call` — and record each node:

- **Hang the spans off events you already have.** The host's hooks (prompt-submit, pre/post tool use,
  sub-agent start/stop, stop, pre-compact) are natural span boundaries — you get the hierarchy without
  instrumenting business logic. claude-kit's own `hooks/` and its orchestrator/sub-agent structure map
  directly onto this tree.
- **Record the attributes that make a run debuggable:** which tool/model, token cost, latency, and
  outcome per node — the same signals §2 monitors and `.claude/rules/quality-gates.md` trends. Capture
  model token usage where the call happens, not by estimating later.
- **Use a stable attribute vocabulary** (a documented convention — e.g. the emerging GenAI semantic
  conventions) so runs stay comparable across sessions and tools, the way `.claude/rules/evals.md`
  needs N-comparable numbers.
- **Record enough to *replay* a node, not merely read it.** Persist each span's input state next to its
  outcome so the run can be resumed from an arbitrary prefix. That is what upgrades a trace from a
  post-mortem artifact into a diagnostic instrument (see error attribution below) — and it is an
  architectural commitment to durable, resumable runs, not a logging flag you flip on later.

This turns "I think the run is progressing" into a measured session you can grade
(`.claude/rules/evals.md`) and trend. (This is *agent-run* telemetry; **app and LLM** observability
live in the `observability-and-logging`, `otel-tracing`, and `langfuse-llm-tracing` skills.)

**Attribute silent failures by intervention, not by retry.** As agents get more capable their dominant
failure mode is *silent*: no exception, no malformed output, no failed gate — the run completes and the
answer is simply wrong. Triage that keys on exceptions, exit codes, or schema violations finds nothing
there, so detection has to be semantic: check the answer, or audit the trace against the §1 criteria.
Attribution then needs care, because **producing a right answer on a second attempt proves nothing about
the first** — a plain retry travels an independent path, so it corrects without explaining. To find the
step that actually mattered, replay from a candidate node with the original prefix intact and one
*specific* hypothesized fix applied; the two trajectories then diverge only at that step, which is what
makes the comparison evidence rather than coincidence. Confirm the replay really followed the hypothesis
before believing an outcome flip — an agent that ignores the patch and succeeds by an unrelated route has
told you nothing. What you are looking for is the earliest **decisive** step (the earliest one whose
correction lets the run finish correctly), not the earliest visible mistake, and it is a *sufficient*
intervention point rather than a proven unique root cause.

Treat this as development-time machinery: it costs several replays per attribution and assumes you can
re-execute a prefix without repeating side effects. It belongs in CI, regression suites over agent
workflows, and eval harnesses (`.claude/rules/evals.md`) — not in live incident response, where
`.claude/rules/agent-resilience.md` and the `incident-responder` path apply instead.

> Stack-agnostic adaptation of intervention-supported error attribution for silent agent failures
> (prefix-preserving replay, faithfulness gating, earliest-decisive-step targeting) from Lin et al.,
> arXiv 2606.09071. Re-derived in prose; the digest lives in the `debugging-and-error-recovery` skill.

**Budget the run before you launch it.** Spend is a criterion too — declare it up front like any
other goal, derived from the orchestration shape: single agent ≈ 1×, maker-checker ≈ 2×,
parallel-N ≈ N+1× (workers + a merge pass), debate-R ≈ 1+R×. Anything over ~2× the single-agent
baseline needs a written justification before tokens go out, not an apology after. Record
**estimate vs actual** in the run telemetry above, and define the **on-exceed action** with the
budget: stop spawning, checkpoint state to `.claude/CONTINUITY.md`, and escalate per
`.claude/rules/human-in-the-loop.md` — never silently run past the number you announced. (Wave-scale
declarations live in `.claude/rules/wave-orchestration.md`'s manifest.)

> Stack-agnostic adaptation of the agent-session instrumentation pattern in the Apache-2.0
> [`alibaba/loongsuite-js`](https://github.com/alibaba/loongsuite-js) (session→turn→tool/LLM span
> hierarchy via runtime hooks, GenAI semantic-convention attributes). Re-derived in prose; not vendored.

## Rules

1. **No work without a checkable goal.** Even a fast-track fix states what "fixed" means and how it's
   proven.
2. **Criteria live in working memory.** Keep them in `.claude/CONTINUITY.md` so they survive
   compaction and the next turn measures against the same bar.
3. **Re-prioritize on new information; don't sunk-cost a stale plan.**
4. **Goal met = every criterion verified**, not "the code is written." Hand off against the criteria.

**This rule is working if** every task names a checkable goal up front, progress is measured against it
rather than assumed, and priorities visibly re-rank when new information lands.

## Relationship to other rules

- **`.claude/rules/rarv-cycle.md`** — Verify proves each criterion; this rule defines the criteria.
- **`.claude/rules/continuity.md`** — where criteria + progress are recorded and monitored.
- **`.claude/rules/quality-gates.md`** — process signals = the monitoring instrumentation.
- **`.claude/rules/human-in-the-loop.md`** — unmeasurable/ambiguous criteria and major re-scoping
  escalate here.
