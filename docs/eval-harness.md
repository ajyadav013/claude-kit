# Eval harness — does the pipeline earn its cost?

A repeatable method to measure what the claude-kit gate pipeline actually *catches* — and what it
costs — by comparing the same tasks run **with** and **without** the pipeline. This is a **template you
fill from your own runs**; the kit deliberately ships **no numbers here**, because an eval result is
only meaningful for the model, tasks, and environment that produced it.

> Method reference: `.claude/rules/evals.md` **§6 (Repeat and aggregate)** — run each case **N times**
> (commonly 5–10) and report the **median**, not the mean, with N stated. This doc does not restate that
> rule; it gives the with/without comparison structure on top of it.

## Design

Two arms over the **same** task set:

- **Arm A — baseline:** the task done by a single agent, no `/sdlc`, no gates (one Developer pass).
- **Arm B — pipeline:** the same task through `/sdlc` at a chosen profile (state which: `lean` /
  `standard` / `enterprise`), with the gates active.

Pick **5–10 representative tasks** with *objective* pass criteria (a hidden test that must pass, a
known breaking change that must be flagged, a secret that must be blocked). Avoid tasks graded by
taste. Run each task **N times per arm** (per `evals.md` §6) and report the **median**.

Keep a third column for **what caught it**: when Arm B succeeds where Arm A fails, name the gate
(`code-review`, `test-coverage`, `security-clear`, `contract-clear`, …) and the severity it assigned.
That is the load-bearing evidence — it converts "the pipeline feels safer" into "gate X caught defect
class Y, Z% of the time."

## Results (fill from your own runs — do not ship fabricated numbers)

> N = ___ runs per arm · model = ___ · profile (Arm B) = ___ · date = ___

| Task | Objective pass criterion | Arm A median (no pipeline) | Arm B median (pipeline) | Gate that caught the gap | Notes |
|------|--------------------------|----------------------------|-------------------------|--------------------------|-------|
| T1 — _e.g._ add endpoint + tests | hidden test suite green | _fill_ | _fill_ | _e.g._ test-coverage (High) | |
| T2 — introduce a breaking API change | change flagged + migration required | _fill_ | _fill_ | contract-clear (High) | |
| T3 — paste a hardcoded secret | secret blocked pre-commit | _fill_ | _fill_ | guard-commit-secrets / security-clear | |
| T4 — … | … | | | | |
| T5 — … | … | | | | |

### Cost

| Arm | Median tokens / task | Median wall-clock / task |
|-----|----------------------|--------------------------|
| A (baseline) | _fill_ | _fill_ |
| B (pipeline) | _fill_ | _fill_ |

> The pipeline costs more per task by design (more agents, more gates). The question this harness
> answers is whether the **defects caught** (and their severity) justify that delta **for your task mix**.

## Skill-activation eval (the routing layer)

The arms above grade what happens *after* a skill or rule fires. A separate failure mode sits in
front of both: does the skill **activate when it should — and stay quiet when it shouldn't**?
Neither arm measures routing; add it as its own small suite.

- **Trigger F1.** Build two prompt lists per skill: *should-activate* (phrasings a real user would
  use) and *should-not-activate* (near-misses from neighboring domains). Run both, score activation
  as binary, report **precision / recall / F1**. A skill with great content and 40% recall is a
  great document nobody reads; one that fires on near-misses taxes every unrelated task.
- **Monte Carlo certification for any number you publish.** Activation is stochastic — run each list
  repeatedly and report the **Wilson confidence interval** on the activation rate, a
  **Clopper-Pearson bound** on the should-activate failure rate (the conservative "at worst" claim),
  and a **bootstrap consistency** check across resamples. "Activates 19/20, 95% CI [86%, 99%]" is a
  claim; "it seems to trigger" is not.

## Falsifiability discipline (before you trust any delta)

- **The falsifiability gate.** Every assertion must **fail in the baseline arm** at least sometimes —
  an assertion that passes in both arms measures the model, not the pipeline, and supports no claim.
  Drop it or sharpen it.
- **Quadrant-classify each row before averaging anything:** **Signal** (fails A, passes B — the
  pipeline earned it) · **Baseline** (passes both — too easy, doesn't count) · **Unreachable**
  (fails both — can't discriminate at this model tier) · **Regression** (passes A, fails B — the
  pipeline *hurt*; investigate before shipping). Only Signal rows support a value claim; every
  Regression row is a finding in its own right.
- **Label delta bands.** Report deltas with a qualitative band (noise / weak / strong at your N)
  rather than celebrating a 3% move the confidence interval can't distinguish from zero.
- **Path-scoped isolation caveat.** If a rule/overlay is path-scoped (loads only when matching files
  are touched), confirm both arms actually touch those paths — otherwise the comparison silently
  measures *activation*, not content.

## Fixed-overhead accounting

Always-injected prose is a **flat tax on every turn**, paid whether or not the content helps that
turn (measure your own install — see `docs/rules-context-budget.md`; even a single always-on rule
file costs on the order of 1–1.5k tokens per turn, and a full rule set far more). So the eval
question is not "does the pipeline help" but "does the help **beat the tax** for your task mix":

- Put the per-turn injected overhead in the Cost table, not only per-task totals.
- The only honest end-to-end number is a **billing A/B** — the same task mix with and without,
  compared on what you were actually charged. Token figures extrapolated from a single run are
  estimates: label them **est.**

## Honesty rules

- **Never publish numbers you did not run.** A "90%" from one run and from twenty runs are not the same
  claim (`evals.md` §6) — always report N.
- An eval result is environment-specific; do not present one repo's table as a general claim about
  claude-kit.
- If a gate caught nothing across the suite, **say so** — that is a signal the gate may be miscalibrated
  for your tasks, which is exactly what this harness is for.
