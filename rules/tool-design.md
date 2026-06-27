# Tool Design (tools & MCP for agents)

When you build a tool, MCP server, script, or slash command for an agent to use, design it for an
**agent consumer**, not a human one. The agent pays tokens for every tool definition it carries and
every byte a tool prints, can't see a GUI, and reasons purely from text. A well-designed tool is as
high-leverage as a well-written prompt — and a badly-designed one quietly burns the context budget and
derails the agent.

> Source: Mario Zechner, "What if you don't need MCP at all?"; Anthropic Engineering, "Building a C
> compiler with a team of parallel Claudes"; "The Anatomy of an Agent Harness." Paraphrased for this kit.

## 1. Prefer small composable tools over heavyweight always-loaded servers

Every persistently-registered MCP server front-loads its whole tool schema into context **every turn**
(often thousands of tokens) whether or not it's used. A small CLI/script the agent calls on demand
costs ~nothing until invoked, and composes — its output can pipe into the next command. Reach for a
persistent MCP server when you genuinely need stateful sessions, pushed events, or auth the agent
can't hold; otherwise prefer a script the agent runs.

## 2. Progressive disclosure

Don't dump every capability up front. Expose a **name + one-line description**; load full usage only
when the tool is actually used (the model behind `.claude/skills/`). This keeps the attention budget on
the task — see `.claude/skills/context-engineering`.

## 3. Name and scope for the model

- **Action-oriented names** that say what the tool does.
- **One clear job per tool** (tight granularity) — a few well-named tools beat many overlapping ones.
- **Self-describing inputs/outputs** in the description, so the agent doesn't guess the contract.

## 4. Design output for a context window

- **Print sparsely.** A few lines of signal inline; write full detail to a file the agent can open if
  it needs to. Dumping a 500-line log into context is how agents lose the thread.
- **Single grep-friendly errors.** Emit failures as one line (`ERROR <reason>`) the agent can scan for.
- **Pre-compute summaries** so the agent reasons from a compact signal, not raw output.
- **Offer a fast/sampled mode** for tight iteration loops where full output isn't needed.

## 5. Structured output for machine consumption

When a result is consumed by code or another agent (not read by a human), return a **typed/validated
structure**, not prose to be re-parsed. Schema-validated output removes a whole class of brittle
string-parsing failures and makes fan-out/verification flows reliable
(`.claude/skills/_references/orchestration-patterns.md`).

## 6. Safe and idempotent

A tool is a **privilege boundary** (`.claude/rules/agent-guardrails.md`): grant least privilege,
validate inputs, make repeated calls safe to retry (idempotent), and gate destructive or
outward-facing actions behind `.claude/rules/human-in-the-loop.md`.

## 7. Spend the resource in proportion to its value

The same token-awareness that shapes a tool's *output* (§4) governs how an agent spends its other
finite resources — parallel dispatch, sourcing calls, and its own response length. Each costs context;
spend each only where it returns value.

> Resource-proportionality heuristics adapted (stack-agnostic) from the MIT-licensed
> [`athola/claude-night-market`](https://github.com/athola/claude-night-market) `conserve` skills
> (`agent-expenditure`, `smart-sourcing`, `response-compression`; © 2025 athola). Not vendored.

- **More agents is not more throughput (Brooks's law for agents).** Coordination overhead grows with
  the parallel count — shared-file conflicts, duplicated reads, reconciliation. Rough guide: 1–3
  agents negligible overhead, 4–5 plan the split first, 6–8 watch closely, 9+ usually
  counterproductive. After a fan-out, ask: did each agent produce *unique* value, was total
  expenditure proportional to it, would fewer have reached the same result? If not, dispatch fewer
  next time. (The parallel-lane model lives in `.claude/rules/mandatory-workflow.md`.)
- **Source only what's worth sourcing.** Verifying a claim costs real tokens — spend them where being
  wrong causes harm *and* the fact changes: versions, performance numbers, security advice, API
  specs, pricing, deprecations. Don't source foundational/common knowledge, syntax, or clearly-framed
  suggestions. When verification isn't cost-effective, mark the uncertainty rather than asserting
  (ties to the `source-driven-development` skill and the "scope the source" guardrail in
  `.claude/rules/agent-guardrails.md`).
- **Keep output dense.** You pay for every byte you emit. Cut filler, hedging-without-reason, hype
  words, and conversational ceremony ("Great question!", "Let me know if…"). Preserve what carries
  signal: status indicators, exact error text, safety warnings, and the context the reader actually
  needs. Density, not coldness — and never at the cost of truthful status
  (`.claude/rules/agent-guardrails.md` §2).

## 8. Design the tool *set* for orchestration, not just each tool in isolation

§1–§7 make one tool good; this makes a *collection* usable by an agent that must chain them toward a
multi-step goal. The set needs four properties:

- **Discoverable from a registry.** Expose the available tools (name + one-line contract, per §2–§3) as
  something the agent can enumerate and select from, rather than a hard-coded call order. New tools
  become usable without rewriting the caller.
- **Plan before execute.** For a multi-step goal, let the agent sequence the calls it intends *first*,
  then run them — not improvise one call at a time. A visible plan is reviewable and surfaces which
  steps are independent (next bullet). (Mirrors `.claude/rules/reasoning-techniques.md`.)
- **Run independent calls concurrently; order only the dependent ones.** Tools with no data dependency
  fan out in parallel; chain only where one output feeds the next — within §7's Brooks's-law caution
  (concurrency has coordination cost).
- **Persist workflow state across turns/steps.** A flow that spans turns or agents needs durable state
  (what's done, what's pending, intermediate results) so it survives a compaction or handoff — the role
  `.claude/rules/continuity.md` plays for the session.

**Write that state atomically.** When a tool or hook persists state to a file another process (a
parallel agent, a concurrent hook) may read or write, **write to a temp file and rename into place** —
a rename is atomic, a half-written direct write is not. Concurrent hooks/agents racing on a shared
state file is a real failure mode; tmp-write-then-rename removes it.

> Orchestration mechanics adapted (stack-agnostic) from the Apache-2.0
> [`alibaba/app-controller`](https://github.com/alibaba/app-controller) (registry-based tool discovery,
> plan-then-execute, concurrent calls, persisted task flows); the atomic state-write rationale from the
> Apache-2.0 [`alibaba/loongsuite-js`](https://github.com/alibaba/loongsuite-js) hook instrumentation.
> Re-derived in prose; not vendored.

## Rules

1. **Design for the agent, not a human dashboard** — text-first, token-aware, self-describing.
2. **Composable-over-heavy** — a script the agent runs beats an always-loaded server unless you need
   state/events/auth.
3. **Sparse output + single-line errors + structured results** are the default, not a nicety.
4. **Eval your tools too** — a tool's effect on agent success is measurable; see `.claude/rules/evals.md`.
5. **Spend in proportion to value** — agents, sourcing calls, and output length are finite context;
   over-dispatching and over-sourcing burn budget without returning it (§7).
6. **Design the tool *set* for orchestration** — discoverable registry, plan-before-execute, concurrent
   independent calls, durable cross-turn state written atomically (tmp-write-then-rename) (§8).

## Relationship to other rules

- **`.claude/rules/agent-guardrails.md`** — tools as privilege boundary; least privilege; gating.
- **`.claude/rules/mandatory-workflow.md`** — the parallel-lane model that §7's Brooks's-law caution
  applies to, and the durable cross-turn state §8 calls for.
- **`.claude/rules/continuity.md`** — durable workflow state across turns/handoffs (§8).
- **`.claude/rules/reasoning-techniques.md`** / **`model-tiers.md`** — tool use is part of how an agent reasons.
- **`.claude/rules/evals.md`** — measure whether a tool change actually helps.
- **`catalog/mcp.yaml`** (kit authors) — where MCP servers are declared and wired into a project.
