---
source: https://arxiv.org/html/2606.09071v1
author: Xiaofeng Lin, Yunxi Wang, Tung Sum Thomas Kwok, Daniel Guo, Sahil Arun Nale, Charles Fleming, Guang Cheng (arXiv 2606.09071v1)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Attribution needs prefix-preserving replay with a targeted patch, not a retry

## What it teaches
Most agent failures in capable systems are *silent*: no tool crash, no malformed
JSON, no exception — the run completes and the answer is simply wrong. The paper
separates two things that teams routinely conflate: **correction** (getting a
right answer on a second try) and **attribution** (knowing which step of the
original run was decisive). Retry, self-reflection, and self-consistency improve
the former and say nothing about the latter, because the successful retry travels
an independent path. The authors set out four requirements for trustworthy
attribution — grounded in actual execution rather than narrative; evidence drawn
from the *same* trace via prefix-preserving replay rather than a fresh attempt;
replay constrained by a diagnosis-specific repair plan rather than bare
resampling; and computed at inference time on the trace in hand rather than
predicted by a pre-trained classifier. Their Reflect pipeline diagnoses a
candidate step, injects a targeted patch and replays from a small neighbourhood
of rollback points, then feeds the verified outcome flip back to *re-localize*.
The output is an attribution record: the step, the intervention applied, and the
verified outcome change.

## Key patterns & decisions
- **Silent failure is the dominant mode as agents get better** — the trace is
  well formed end to end and only the semantics are wrong. Any triage process
  that keys on exceptions, non-zero exits, or schema violations will find
  nothing. Detection has to be semantic (answer check, plan-anchored audit),
  not structural.
- **Correction is not attribution** — a system that recovers the right answer by
  resampling has proven nothing about the original run. The paper's coupling
  metric makes this measurable: explanation quality for corrected versus failed
  traces differs by only +0.03 for a backtracking baseline and +0.05 for
  Reflexion, versus +0.25 to +0.29 for the intervention-coupled method.
- **Prefix-preserving replay is the source of the evidence** — re-running from
  step *i* with the original prefix intact means the two trajectories share
  everything before *i* and diverge only there, which is what makes the
  comparison contrastive. An independent retry cannot produce that structure.
- **Define the target operationally: the earliest *decisive* step** — not the
  earliest mistake. Traces contain multiple correlated errors, and the useful
  one is the earliest step whose correction enables a verified-correct
  continuation. The paper is explicit that this establishes sufficiency, not
  causal minimality or uniqueness.
- **A structured repair plan beats a vague hint** — the diagnostician emits root
  cause, a correction instruction, forbidden actions, and the expected next tool.
  Ablation puts the diagnostician as the single biggest lever on correction rate
  (about +28 pp), while multi-point rollback mainly helps localization.
- **A faithfulness gate separates a targeted test from a lucky retry** — the gate
  checks whether the first regenerated step actually follows the plan; if the
  agent ignores the patch and succeeds by an unrelated route, the flip is not
  evidence about the hypothesized step. Rule-based filter first, LLM judgment
  only when needed; soft mode logs, hard mode rejects and retries.
- **Roll back to a small neighbourhood, not a single index** — localization is
  routinely off by one or two, so replaying from a window of K candidate points
  recovers from near-misses while preserving as much original prefix as
  possible.
- **Placebo and wrong-step controls are how you prove the signal is real** — a
  semantically correct hint lifted correction accuracy by roughly 42 pp over no
  hint and 32 pp over a placebo hint of similar length, and intervening at a
  deliberately wrong step (mean distance 2.6) dropped accuracy to about 46%
  while plan adherence stayed high. The target, not the act of intervening,
  drives the fix.
- **Without a ground-truth answer, attribution degrades gracefully but unevenly**
  — a plan-anchored verifier that synthesizes task anchors from the question
  alone reached AUROC 0.968 on software-engineering traces and 0.842 on
  multi-hop reasoning, but only 0.561 on bare chain-of-thought, where there is
  no tool-call structure to anchor against.

## When to apply / trade-offs
This is development-time debugging machinery: it assumes you can re-run the agent
from an arbitrary prefix and that you have a checkable expected output — CI
pipelines, regression suites over agent workflows, evaluation harnesses, and any
task with deterministic or strongly verifiable results. The cost is real: each
attribution runs a diagnosis, several replays across rollback points, a
faithfulness gate, and up to D diagnosis rounds, so it is orders of magnitude
more expensive than asking a judge model to point at a step. It also needs a
replayable agent — durable, resumable traces where you can inject guidance at a
chosen step — which is an architectural commitment, not a bolt-on. Do not reach
for it in live production incident response, where you cannot re-execute side
effects; do not expect much from it on unstructured chain-of-thought traces,
where the paper's own numbers are weakest and a strong judge model beat it. And
do not over-read the result: the attributed step is a sufficient intervention
point, not necessarily the unique root cause, and single-step attribution is
ill-posed when the failure is distributed across many steps.

## Fidelity check
1. Claim: correction and attribution are distinct, and the coupling gap is about
   +0.03 to +0.05 for retry-style baselines versus +0.25 to +0.29 for Reflect.
   Support: the correction–localization coupling table reports explanation
   similarity split by corrected versus failed traces with exactly those deltas.
2. Claim: a correct repair hint gained roughly 42 pp of correction accuracy over
   no hint and 32 pp over a placebo, and intervening at a wrong step (mean
   distance 2.6) dropped accuracy to about 46% while adherence stayed near 60%.
   Support: the faithfulness-results table on 119 table-QA examples lists
   correct hint 78.7%, placebo 46.3%, no hint 35.6%, wrong-step 46.2% with
   60.3% adherence, and the text gives the +42.0 / +32.0 pp figures.
3. Claim: no-oracle verification quality varies sharply by trace structure —
   AUROC 0.968 on software-engineering traces versus 0.561 on chain-of-thought.
   Support: the plan-anchored verifier detection table lists those AUROC values
   per benchmark, and the text ties the gap to the absence of tool-call
   structure.
