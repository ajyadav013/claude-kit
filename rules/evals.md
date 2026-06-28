# Evals (Evaluation-Driven Development)

How to measure the quality of **AI/agent-powered features** — anything whose output is produced by a
model and is therefore non-deterministic. You cannot assert these with ordinary unit tests; you
*grade* them. An **eval** is a small, graded set of representative tasks you run to measure
quality/cost/latency before and after a change. Treat evals as the **unit of progress**: if you can't
measure it, you're iterating blind.

This is distinct from `.claude/rules/testing.md` — that rule covers deterministic product tests
(same input → same output, assert exactly). *This* rule covers probabilistic model/agent behavior
(same input → a distribution of outputs, grade against criteria).

> Source: Anthropic Engineering, "Demystifying evals for AI agents"; Cursor, "Bench" (internal eval
> suites for agent harnesses). Paraphrased for this kit.

## 1. Build the eval set before iterating

Start tiny (≈20–100 cases) and representative. Each case = an input plus a **grader** (an expected
outcome, or a rubric). Grow the set from **real failures** — every production miss becomes a new case.
A small graded set you actually run beats a large one you don't.

## 2. Grade outcomes, not paths

An agent legitimately reaches a goal many ways. Grade the **final state / output** against criteria,
not a required tool sequence. Over-constraining the path produces false failures and punishes valid
strategies. (Mirror of the RARV "verify the result" stance in `.claude/rules/rarv-cycle.md`.)

## 3. Choose the grader deliberately

- **Code / exact** graders for deterministic outputs (a value, a file state, a passing build).
- **LLM-as-judge** for open-ended outputs — but **calibrate the judge against human labels** on a
  sample first. An uncalibrated judge confidently mis-scores and you optimize toward the wrong thing.
  For multi-dimensional quality, give the judge an explicit **weighted rubric** (named criteria whose
  weights sum to 1, each with a score band → meaning) rather than a vague "rate this 1–10": a
  documented rubric scores consistently across runs and makes a low score *explainable*. Keep the
  rubric for *grading*; the pipeline's pass/fail **gate** stays binary (§6, `quality-gates.md`).
- **Human** grading for the highest-stakes or subjective cases; use it to keep the automated graders honest.

Two refinements when one judge isn't enough:

- **Panel of judges for multi-dimensional or high-stakes scoring.** Instead of one judge rating
  everything on a vague scale, run a small **assembly** of specialized judges (each with its own narrow
  rubric, optionally its own model) in parallel and **aggregate** — report the median and the
  inter-judge agreement, and add a **mediator** ("super-judge") pass to reconcile genuine disagreement
  into one verdict. Diverse judges catch failure modes a single judge is blind to (the eval-side mirror
  of multi-agent blind review in `.claude/rules/quality-gates.md`).
- **Grade tool-use and response-quality on separate axes (agentic features).** An agent run can call
  the right tools but answer poorly, or answer plausibly via a wrong/unsafe path. Score the two as
  **independent** pass/fail dimensions so a good final answer can't mask bad tool behavior, and vice
  versa — don't collapse them into one number.

> Multi-judge assembly + super-judge mediation, and the tool-use-vs-response-quality split, are
> stack-agnostic adaptations of the MIT [`microsoft/llm-as-judge`](https://github.com/microsoft/llm-as-judge)
> and [`microsoft/EvalsforAgentsInterop`](https://github.com/microsoft/EvalsforAgentsInterop).
> Re-derived in prose; not vendored.

## 4. Report non-determinism honestly

- **pass@k** — probability of ≥1 success in k tries. Rises with k. Use when the user can retry.
- **pass^k** — probability that **all** k succeed. Falls with k. Use when reliability matters
  (automated/production runs, gates).

They diverge as k grows (75% per-trial ≈ 42% over three trials for pass^3). Report **both**, and pick
the one that matches how the feature is actually used.

## 5. Keep two suites

- **Regression** — locks in behaviors that must not break; a drop **fails the gate**
  (`.claude/rules/quality-gates.md`).
- **Capability** — pushes the frontier; tracks progress on hard cases you don't pass yet.

## 6. Run repeated trials, and split measurement from gate

A single run of a non-deterministic feature tells you almost nothing. Two practices keep the numbers
honest:

- **Repeat and aggregate.** Run each case **N times** (commonly 5–10) and report the **median**, not
  the mean — the median is robust to the occasional wild outlier a model produces. Report N alongside
  the result; a "90%" from one run and from twenty runs are not the same claim.
- **Separate metrics that *measure* from metrics that *gate*.** A **measurement** metric records a
  number and always passes (lines of code, token cost, latency, output length) — it's there to track a
  trend, not to block. A **gate** metric actually exercises the output and **fails** when it breaks
  (run the generated code, assert the result, check the file state). Don't let a measurement masquerade
  as a gate: a solution that scores beautifully on "fewer lines" but doesn't run must still **fail**,
  because the correctness gate executed it. Wire only gate metrics into `.claude/rules/quality-gates.md`;
  keep measurements as dashboards.

> Worked example: the [ponytail](https://github.com/DietrichGebert/ponytail) benchmark runs 3 arms ×
> 3 models × 5 tasks at 10 runs each (median reported), with a line-count *measurement* that always
> passes beside a *correctness gate* that spawns the runtime to actually execute the generated code.
> A concrete instance of this section's two practices.
>
> To measure the **claude-kit pipeline itself** (the same tasks run with vs without the gates, and
> which gate caught each defect), the claude-kit repo ships a fill-in template — `docs/eval-harness.md`
> — that builds the with/without comparison on top of this section's median-of-N method.

## 7. Stage the eval: sequential gates, leak-resistant, objectively anchored

When the thing under eval is generated code (or any artifact with a hard correctness floor), structure
the eval as **ordered gates where each must pass before the next is even measured**, and isolate
generation from grading so the model can't see what it's graded against.

- **Sequential gating.** Run the cheap, decisive checks first and let each gate the next: does it
  **build/compile** → does it produce the **correct result** → only then, how **efficient** is it. A
  solution that fails an earlier gate scores zero on the later ones — you never report a performance
  number for output that doesn't run. This stops early (saves cost) and kills the classic false win of
  optimizing an answer that was never correct (mirrors §6's "a measurement is not a gate").
- **Leak-resistant separation.** The model must not be able to read what it is graded against. Keep
  generation and grading in **separate sessions / working directories**, and **strip** expected
  outputs, reference solutions, baselines, and grader source from anything the model can see before it
  generates. An eval the model can read the answer to measures retrieval, not capability.
- **Anchor to an objective baseline, not self-assessment.** Score against an **external, pre-computed
  reference** — a known-good output, a measured baseline, or a theoretical limit (e.g. a
  roofline/speed-of-light bound) — rather than letting the model grade its own work. Cache the baseline
  so the comparison is stable run-to-run (the same stability §6's median-of-N gives the score).

> Stack-agnostic adaptation of the staged-evaluator pattern in the Apache-2.0
> [`alibaba/atrex-bench`](https://github.com/alibaba/atrex-bench) (compile→correctness→performance
> gating, generate/eval session isolation, cached roofline baselines). Re-derived in prose; not vendored.

## 8. Evaluate multi-turn behavior, not just single-shot answers

A model that scores well on one-shot prompts can still **degrade sharply across a conversation** —
accuracy measured turn-by-turn drops well below the single-turn number once the task is delivered
piecemeal, context accumulates, and the model commits early to a wrong assumption it never revisits.
A single-turn eval will not catch this; claude-kit's own agents run over long multi-turn sessions
(plan → implement → review), so it matters here.

- **Shard a single-turn case into turns.** Take a task you already grade single-shot and split its
  requirements across several user turns (reveal constraints incrementally). Run both forms and compare
  the final-state score — the **single-turn vs multi-turn gap** is the degradation metric.
- **Watch for early lock-in.** The dominant failure is the model latching onto an early, under-specified
  guess and never correcting as later turns add information. An eval that surfaces this tells you to add
  a re-grounding step (re-read the accumulated requirement before acting) — the `context-engineering`
  "compact/clash" fixes apply.
- **Report it like §6.** Multi-turn runs are *more* non-deterministic, not less; use median-of-N and
  report both single- and multi-turn numbers — a "90% single-turn" feature that is "55% multi-turn" is
  two different claims.

> Stack-agnostic adaptation of the conversation-degradation measurement (task-sharding,
> single-vs-multi-turn comparison) in the MIT
> [`microsoft/lost_in_conversation`](https://github.com/microsoft/lost_in_conversation). Re-derived in
> prose; not vendored.

## Rules

1. **No prompt/rule/tool/model change ships without an eval run** that covers the affected behavior.
2. **Evals are how you adopt a new model.** Re-run the suite before re-tiering an agent
   (`.claude/rules/model-tiers.md`); a cheaper model that holds the eval is a free win.
3. **Evals are living infrastructure with an owner** — versioned, in the repo, run in CI where possible.

## Relationship to other rules

- **`.claude/rules/testing.md`** — deterministic product tests; evals are its probabilistic sibling.
- **`.claude/rules/goal-setting-and-monitoring.md`** — eval pass-rates are measurable success criteria.
- **`.claude/rules/quality-gates.md`** — a regression-eval drop is a gate-failing signal.
- **`.claude/rules/model-tiers.md`** — re-run evals before changing an agent's model.
