---
source: https://arxiv.org/html/2605.12239v1
author: Bogdan Banu — arXiv preprint 2605.12239v1 (cs.PL, May 2026), CC BY 4.0
license-note: ideas absorbed in own words; no text or code reproduced
---

# A harness's guarantees belong to its structure, not its model

## What it teaches
The paper argues that the "harness" practitioners talk about — prompts, tools,
memory, orchestration, safety checks — already has a formal shape: an
Architecture triple of syntactic wiring (G), a knowledge/invariant structure
(Know), and a deployment map (Φ) from abstract capability slots to concrete
models. The four externalization pillars line up one-to-one: memory is
coalgebraic state, skills are objects composed by an operad, protocols are the
wiring graph, and the harness is the whole triple rather than one part of it.
The load-bearing move is putting structural guarantees — a priority gate, a
quality-escalation rule, a convergence bound — into Know as *certificates*: a
theorem, a binding of its symbols to architecture parameters, and evidence that
can be mechanically replayed. Because certificates live in Know and the model
lives in Φ, changing the model does not invalidate them, and compiling the
harness to another framework preserves them provided the compiler carries the
theorem, parameters, and evidence across and re-verifies. The author checks
this over five compiler targets and reports honest negatives elsewhere: the
architecture bought preservation and primitive reuse, not task-resolution gains.

## Key patterns & decisions
- **Separate what you guarantee (Know) from what you run it on (Φ)** — the
  deployment map assigning each stage a model tier is a *parameter* of the
  architecture, not a constant. Two deployments can share wiring and invariants
  while differing entirely in model choice, which is what makes a harness
  genuinely model-parametric instead of accidentally tuned to one model.
- **A guarantee is only real if it is mechanically replayable** — the
  certificate is defined as a triple of theorem statement, a mapping from
  theorem symbols to architecture parameters, and a derivation that can be
  re-run to check the theorem still holds. "Add a safety check" is not a
  guarantee; a named, parameterised, re-verifiable claim is.
- **Structure-preserving translation is not enough — check identity and replay
  explicitly** — the author treats functor laws as insufficient evidence for a
  preservation claim and makes the compiler assert three things separately:
  source stages and edges are a subset of target stages and edges, source
  certificate theorems/parameters/evidence survive and re-verify true, and the
  deployment map's stages are present in the target.
- **Compile by reusing the runtime's own per-stage step, never by reimplementing
  it** — an earlier attempt that re-encoded component logic as native nodes of
  the target framework needed ten rounds of code review to reach behavioural
  parity. Extracting a single per-stage method and calling it from both the
  native loop and each compiled node removed the divergence class entirely, and
  gave target-native observability for free.
- **Topology may change; guarantees need not** — of the five targets, two kept
  per-stage structure, one reshaped to hub-and-spoke, one converted stages into
  role "hats", and one added a watcher agent. All three certificate types still
  verified, because the certificates depended on preserved hooks and parameters
  rather than on the exact graph shape.
- **Three composition operators, with a closure caveat** — serial, parallel
  (disjoint state), and trace (feedback loop). Composition preserves a property
  only when that property is closed under the operator used; the cited
  empirical finding that five atomic coding skills (localize, edit, test,
  reproduce, review) train jointly without interference is presented as
  consistent with this, not as proof of it.
- **Type the wires, and label their integrity** — ports carry types and each
  port carries an integrity label (raw, sanitized, validated), with wire-level
  access patterns for scoped read, conditional routing, and batch traversal.
  Trust state becomes a checkable property of the graph rather than a comment.
- **Bi-temporal memory buys you belief reconstruction** — every fact carries
  both the time it was true in the world and the time the system learned it, so
  you can reconstruct after the fact what the agent knew at the moment it made a
  given decision. That is the difference between memory as a store and memory as
  state with update rules.
- **Quality-triggered escalation is a harness primitive, not a model trick** —
  a rubric verifier scored a small model's code review at 0.50 against a 0.60
  threshold, a watcher fired ESCALATE, and the larger model re-ran the same
  stage. Independent task validation showed the rubric discriminates (0.72 vs
  1.00 across the two models, a 0.28 delta against a 0.20 bar).
- **Decomposition does not relax a capability ceiling** — on ten SWE-bench-lite
  instances with two local 8B Q4_K_M models, zero instances resolved under
  direct prompting, three-stage decomposition, or compiled execution. Adding
  repository grounding raised baseline mean latency from 44 s to 131 s with no
  gain, and a reason-coded format-correction retry recovered 0 of 30 rejected
  submissions — 26 of those had produced no diff-shaped output at all, so the
  retry was aimed at the wrong failure regime.

## When to apply / trade-offs
Reach for this when you expect a harness to outlive a specific model or
framework: multi-model deployments, a planned migration between orchestrators,
or a safety property (a gate, a bound, a routing rule) that someone must be
able to audit later. The discipline it demands is real work up front — naming
each guarantee, binding it to concrete parameters, and writing a verifier that
can replay it — and the paper is candid that this bought preservation and
primitive reuse, not better task outcomes. Skip it for a single-model
throwaway agent, and do not expect it to cover behavioural claims: the
certificates here are structural invariants like priority gating and
convergence, explicitly not properties like "the agent never hallucinates".
Note also that all validation runs on one reference codebase, the framework is
a static snapshot with no account of harnesses that adapt over time, and the
escalation evidence is two models on one task. Treat the certificate discipline
as the transferable part and the specific numbers as one lab's data point.

## Fidelity check
1. Claim: guarantees live in Know while the model lives in Φ, so swapping the
   model does not invalidate them. Support: the capture defines Φ as a map from
   stages to model tiers and states it is a parameter of the architecture rather
   than a fixed constant, with different deployments able to vary Φ while
   preserving the same (G, Know).
2. Claim: topology changed across targets while certificates still verified.
   Support: the capture's compiler table shows per-stage structure preserved for
   two targets, hub-and-spoke reshaping, conversion to hats, and an added
   watcher — with 100% certificate preservation in every row, and 3/3 verified
   for each of the four measured configuration compilers.
3. Claim: the escalation experiment scored 0.50 against a 0.60 threshold and
   escalated, with a 0.28 discrimination delta. Support: the capture reports the
   fast model at quality 0.50, the watcher decision 0.50 < 0.60 → ESCALATE, and
   separately the 0.72 vs 1.00 validation scores against a 0.20 threshold.
