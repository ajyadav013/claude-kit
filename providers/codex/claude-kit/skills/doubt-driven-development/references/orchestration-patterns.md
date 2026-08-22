# Orchestration Patterns

Reference catalog of agent orchestration patterns this repo endorses, plus anti-patterns to avoid. Read this before adding a new explicit workflow skill that coordinates multiple personas, or before introducing a new persona that "wraps" existing ones.

The governing rule: **the user (or a explicit workflow skill) is the orchestrator. Personas do not invoke other personas.** Skills are mandatory hops inside a persona's workflow.

---

## Endorsed patterns

### 1. Direct invocation (no orchestration)

Single persona, single perspective, single artifact. The default and the cheapest option.

```
user → code-reviewer → report → user
```

**Use when:** the work is one perspective on one artifact and you can describe it in one sentence.

**Examples:**
- "Review this PR" → `code-reviewer`
- "Find security issues in `auth.ts`" → `security-auditor`
- "What tests are missing for the checkout flow?" → `test-engineer`

**Cost:** one round trip. The baseline you should always compare orchestrated patterns against.

---

### 2. Single-persona explicit workflow skill

A explicit workflow skill that wraps one persona with the project's skills. Saves the user from re-explaining the workflow every time.

```
the review skill → code-reviewer (with code-review-and-quality skill) → report
```

**Use when:** the same single-persona invocation happens repeatedly with the same setup.

**Examples in this repo:** `the review skill`, `the test skill`, `the code-simplify skill`.

**Cost:** same as direct invocation. The explicit workflow skill is just a saved prompt.

**Anti-signal:** if the explicit workflow skill's body is mostly "decide which persona to call," delete it and let the user call the persona directly.

---

### 3. Parallel fan-out with merge

Multiple personas operate on the same input concurrently, each producing an independent report. A merge step (in the main agent's context) synthesizes them into a single decision.

```
                    ┌─→ code-reviewer    ─┐
the ship skill → fan out  ───┼─→ security-auditor ─┤→ merge → go/no-go + rollback
                    └─→ test-engineer    ─┘
```

**Use when:**
- The sub-tasks are genuinely independent (no shared mutable state, no ordering dependency)
- Each sub-agent benefits from its own context window
- The merge step is small enough to stay in the main context
- Wall-clock latency matters

**Examples in this repo:** `the ship skill`.

**Cost:** N parallel sub-agent contexts + one merge turn. Higher than direct invocation, but faster wall-clock and produces better reports because each sub-agent stays focused on its single perspective.

**Validation checklist before adopting this pattern:**
- [ ] Can I run all sub-agents at the same time without ordering issues?
- [ ] Does each persona produce a different *kind* of finding, not just the same finding from a different angle?
- [ ] Will the merge step fit in the main agent's remaining context?
- [ ] Is the user's wait time long enough that parallelism is actually noticeable?

If any answer is "no," fall back to direct invocation or a single-persona command.

---

### 4. Sequential pipeline as user-driven explicit workflow skills

The user runs explicit workflow skills in a defined order, carrying context (or commit history) between them. There is no orchestrator agent — the user IS the orchestrator.

```
user runs:  the spec skill  →  the plan skill  →  the build skill  →  the test skill  →  the review skill  →  the ship skill
```

**Use when:** the workflow has dependencies (each step needs the previous step's output) and human judgment between steps adds value.

**Examples in this repo:** the entire DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP lifecycle.

**Cost:** one sub-agent context per step. Free for the orchestration layer because there is no orchestrator agent.

**Why not automate it:** an LLM "lifecycle orchestrator" would (a) lose nuance between steps because it has to summarize for hand-off, (b) skip the human checkpoints that catch wrong-direction work early, and (c) double the token cost via paraphrasing turns.

---

### 5. Research isolation (context preservation)

When a task requires reading large amounts of material that shouldn't pollute the main context, spawn a research sub-agent that returns only a digest.

```
main agent → research sub-agent (reads 50 files) → digest → main agent continues
```

**Use when:**
- The main session needs to stay focused on a downstream task
- The investigation result is much smaller than the input it consumes
- The decision quality benefits from the main agent having room to think after

**Examples:** "Find every call site of this deprecated API across the monorepo," "Summarize what these 30 ADRs say about caching."

**Cost:** one isolated sub-agent context. Worth it any time the alternative is loading hundreds of files into the main context.

**Use a host-native read-only research worker when available.** Otherwise delegate with an explicit read-only scope and require a compact digest.

---

## Host compatibility

Map each persona to a host-native delegated worker when one is available. If
named agents or teammate messaging are unavailable, embed the persona's
instructions in a generic delegated task. Treat nested delegation, shared task
lists, and teammate messaging as capability-gated; keep orchestration in the
main session when a capability is absent. Parallel fan-out still requires
independent workers and one explicit merge in the main session.

---

## Anti-patterns

### A. Router persona ("meta-orchestrator")

A persona whose job is to decide which other persona to call.

```
the work skill → router-persona → "this needs a review" → code-reviewer → router (paraphrases) → user
```

**Why it fails:**
- Pure routing layer with no domain value
- Adds two paraphrasing hops → information loss + roughly 2× token cost
- The user already knew they wanted a review; they could have called `the review skill` directly
- Replicates the work that explicit workflow skills and intent mapping in `AGENTS.md` already do

**What to do instead:** add or refine explicit workflow skills. Document intent → command mapping in `AGENTS.md`.

---

### B. Persona that calls another persona

A `code-reviewer` that internally invokes `security-auditor` when it sees auth code.

**Why it fails:**
- Personas were designed to produce a single perspective; chaining them defeats that
- The summary the calling persona passes loses context the called persona needs
- Failure modes multiply (which persona's output format wins? whose rules apply?)
- Hides cost from the user

**What to do instead:** have the calling persona *recommend* a follow-up audit in its report. The user or a explicit workflow skill runs the second pass.

---

### C. Sequential orchestrator that paraphrases

An agent that calls `the spec skill`, then `the plan skill`, then `the build skill`, etc. on the user's behalf.

**Why it fails:**
- Loses the human checkpoints that catch wrong-direction work
- Each hand-off summarizes context — accumulated drift over a long pipeline
- Doubles token cost: orchestrator turn + sub-agent turn for every step
- Removes user agency at exactly the points where judgment matters most

**What to do instead:** keep the user as the orchestrator. Document the recommended sequence in `README.md` and let users invoke it.

---

### D. Deep persona trees

`the ship skill` calls a `pre-ship-coordinator` that calls a `quality-coordinator` that calls `code-reviewer`.

**Why it fails:**
- Each layer adds latency and tokens with no decision value
- Debugging becomes a multi-level investigation
- The leaf personas lose context to multiple summarization steps

**What to do instead:** keep the orchestration depth at most 1 (explicit workflow skill → personas). The merge happens in the main agent. (Deliberate exception: the `sdlc` pipeline's contract — main session → orchestrator(s) → workers — carries its depth by design; this anti-pattern targets ad-hoc persona trees, not that contract.)

---

## Decision flow

When considering a new orchestrated workflow, walk this flow:

```
Is the work one perspective on one artifact?
├── Yes → Direct invocation. Stop.
└── No  → Will the same composition repeat?
         ├── No  → Direct invocation, ad hoc. Stop.
         └── Yes → Are sub-tasks independent?
                  ├── No  → Sequential explicit workflow skills run by user (Pattern 4).
                  └── Yes → Parallel fan-out with merge (Pattern 3).
                           Validate against the checklist above.
                           If any check fails → fall back to single-persona command (Pattern 2).
```

---

## Why these patterns work: the failure modes they counter

Single-context, single-agent execution drifts in predictable ways. The endorsed patterns exist to
counter three recurring failure modes — name them so you can spot which pattern a situation needs:

- **Agentic laziness** — the agent declares done early ("35 of 50 handled") or takes the cheap path.
  *Counter:* isolation (a fresh sub-agent per item) + a loop with an explicit completion check.
- **Self-preferential bias** — the agent rates its own output highly when asked to judge it.
  *Counter:* a **separate** verifier (the independent-verifier pattern), ideally each verifier
  given a **distinct failure-mode lens** (correctness vs. security vs. performance) rather than N
  identical checks — diversity catches what redundancy can't.
- **Goal drift** — after a long run or a lossy compaction, the agent loses the original objective.
  *Counter:* re-state the goal/acceptance criteria into each sub-agent's fresh context, and keep
  orchestration depth flat (≤1) so hand-offs don't accumulate paraphrase.

## Programmatic orchestration (the Workflow / harness layer)

The patterns above are about **personas** — the user or a explicit workflow skill orchestrates subagents. A
second, lower-level layer exists when you drive fan-out **programmatically** from a single orchestrator
(e.g. a host workflow runner runs a script that spawns and joins many subagents). The same
isolation principle applies, plus a few composable shapes worth knowing:

- **fan-out-and-synthesize** — split a work-list, run each item in its own context, merge results.
- **generate-and-filter** — over-generate candidates, then a rubric/verifier keeps the best.
- **tournament** — pairwise/bracket comparison when you need the single best of many.
- **loop-until-done / loop-until-dry** — repeat until a completion (or "no new findings") check passes;
  the direct counter to agentic laziness.

Use this layer for large, repetitive, or adversarial work (migrations, broad audits, deep research). It
costs more than a single pass — reserve it for high-value tasks and prefer the persona patterns above
for ordinary work. Pair it with `.ckit/rules/evals.md` to confirm the extra cost actually buys quality.

> Source: "A harness for every task: dynamic workflows in an agent harness"; "Building a C compiler with a
> team of parallel assistants." Paraphrased for this kit.

## When to add a new pattern to this catalog

Add a new entry only after:

1. You've used the pattern at least twice in real work
2. You can name a concrete artifact in this repo that demonstrates it
3. You can explain why an existing pattern wouldn't have worked
4. You can describe its anti-pattern shadow (what people will mistakenly build instead)

Premature catalog entries become aspirational documentation that no one follows.
