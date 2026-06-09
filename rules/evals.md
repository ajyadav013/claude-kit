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
- **Human** grading for the highest-stakes or subjective cases; use it to keep the automated graders honest.

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
