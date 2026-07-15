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

**Audit what's actually loaded before a substantial run.** A persistent server's cost is not paid
once — its schema re-enters context **every turn, for every subagent** that inherits the config, so
one unused server taxes an entire fan-out multiplicatively. The harness exposes per-project switches
(`enabledMcpjsonServers` / `disabledMcpjsonServers` in settings) precisely so a project can *carry* a
server in `.mcp.json` yet keep it out of context until a task needs it. Make the audit a pre-run
habit: list what's enabled, disable what this run won't use, re-enable on demand.

> Pre-run MCP audit pattern from [`mksglu/context-mode`](https://github.com/mksglu/context-mode).
> Referenced, not vendored.

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
- **Compress at the source — ask for less before trimming what came back.** Most tools already have a
  compact mode; make it the one the agent reaches for first: failures-only test output, `--quiet` /
  `--porcelain` / summary flags, JSON narrowed by a selector instead of a full dump, repeated lines
  deduplicated to one line with a count, and a **one-line acknowledgement for success** (a passing
  step needs "OK" and a number, not its full log). Filtering after the fact still paid for the tokens;
  the compact flag never emits them.
- **Make every compression reversible.** When a tool truncates, samples, or dedups, it must write the
  full original to a file and leave an inline marker carrying the dropped-item **count** and the
  **retrieval path** — never silently drop items. A compression the agent can't undo is a deletion.
  (The consumer-side twin of this rule lives in `.claude/skills/context-engineering`.)

> Source-side compaction (compact flags, dedup-with-count, one-line success acks) adapted from the
> Apache-2.0 [`rtk-ai/rtk`](https://github.com/rtk-ai/rtk); the reversible-marker discipline from the
> Apache-2.0 [`headroomlabs-ai/headroom`](https://github.com/headroomlabs-ai/headroom). Re-derived in
> prose; not vendored.

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
state file is a real failure mode; tmp-write-then-rename removes it. Three gotchas make the difference
between *looks* atomic and *is* durable:

- **Atomicity ≠ durability.** Rename guarantees a reader never sees a half-written file; it does **not**
  guarantee the bytes survive a crash. If the state must outlive a power loss, **`fsync` the temp file
  before the rename** (otherwise a crash can leave the renamed file present but empty / zero-length —
  the classic "0-byte file after crash" bug).
- **Same filesystem.** The temp file must be on the *same* filesystem as the destination, or the
  "rename" becomes a copy that is no longer atomic. Create the temp beside the target, not in `/tmp`.
- **Track the temp for cleanup.** On the error path, remove the temp file you created — don't leak a
  `.tmp-XXXX` next to every state file when a write fails partway.

> Atomic-write durability nuances (atomicity-vs-durability, fsync-before-rename, same-fs, temp cleanup)
> are a stack-agnostic adaptation of the Apache-2.0
> [`google/renameio`](https://github.com/google/renameio). Re-derived in prose; not vendored.

> Orchestration mechanics adapted (stack-agnostic) from the Apache-2.0
> [`alibaba/app-controller`](https://github.com/alibaba/app-controller) (registry-based tool discovery,
> plan-then-execute, concurrent calls, persisted task flows); the atomic state-write rationale from the
> Apache-2.0 [`alibaba/loongsuite-js`](https://github.com/alibaba/loongsuite-js) hook instrumentation.
> Re-derived in prose; not vendored.

## 9. Anchor edits to content, not position

A tool that edits files on an agent's behalf must verify it is editing **what the agent last saw**,
not whatever now sits at the same coordinates. Line numbers and byte offsets go stale the moment a
formatter, a hook, or a parallel agent touches the file — and a stale-anchor edit silently corrupts
the one thing the agent believed it controlled.

- **Capture a content hash at read time; re-verify at apply time.** When the agent reads the region it
  intends to edit, record a hash (or the exact text) of that region. On apply, re-hash: on mismatch,
  **fail fast with a report of what changed** — never apply to drifted content. The agent then
  re-reads and re-anchors; anything smarter (fuzzy re-matching) is a conservative, opt-in recovery
  mode, never the default.
- **Treat a no-op edit as a signal, not a success.** If applying an edit produces byte-identical
  output, the premise behind the edit was wrong — return "no change made; the bug is likely elsewhere"
  instead of a success code. **N consecutive no-op edits is a hard error**: the agent is spinning on a
  false belief about the file, and every hollow "success" reinforces it.

> Hash-anchored edits and the no-op escalation guard adapted (stack-agnostic) from the MIT-licensed
> [`can1357/oh-my-pi`](https://github.com/can1357/oh-my-pi). Re-derived in prose; not vendored.

## 10. Write the tool description like an API contract, not an implementation tour

The description is the only part of your tool the model reads before deciding to call it. It is a
prompt, and it deserves prompt-quality authoring.

- **Describe the surface, not the machinery.** What the tool does, takes, and returns — never how it
  works inside. Internals the agent can't act on are pure token cost, and worse, they invite the
  agent to reason about (and route around) the implementation.
- **Six-part anatomy** for any non-trivial tool: (1) a one-sentence **purpose**; (2) the **input
  grammar** — exact shapes, defaults, units; (3) **3–8 worked examples** spanning easy to edge case
  (one example is a special case the model overfits to; zero is a guess); (4) the **failure shapes the
  agent owns** — which errors it should handle itself, and how; (5) **WRONG/RIGHT anti-pattern pairs**
  for misuse you have actually observed; (6) a one-line **recap** of the contract.
- **Prune on evidence, never on inferability.** "The model could infer this" is necessary but never
  sufficient to cut a line — check history (`git blame` / log) first: description lines are often
  load-bearing fixes for a failure someone already debugged. Cut only what you can show never fires.

> Description anatomy and evidence-based pruning adapted (stack-agnostic) from the MIT-licensed
> [`gsd-build/get-shit-done`](https://github.com/gsd-build/get-shit-done). Re-derived in prose; not
> vendored.

## 11. Errors an agent can parse — and denials an agent can act on

§4 makes errors single-line and grep-able; this section fixes their **content**. An agent recovers
from a failure exactly as well as the error message lets it.

- **Split the envelope.** Success and error must be structurally distinguishable — distinct exit
  codes, or a status field in structured output — never left for the agent to infer from prose.
- **Wire-stable category, free informational text.** Give every failure a short **category ID** that
  retry logic can branch on (`NOT_FOUND`, `PERMISSION`, `CONFLICT`, …) and keep it stable across
  releases; the human-readable message may change freely. Derive exit codes from the category, not
  ad hoc per call site.
- **Actionable hint with the exact recovery command.** "Auth expired — run `<tool> login`" lets the
  agent self-recover in one step; "authentication error" starts a guessing loop.
- **Never surface an upstream success flag as your own.** A wrapper that reports success because the
  transport returned `code == 0` while the payload carries an error teaches the agent the operation
  worked. Branch on the payload's own contract, not the carrier's.

**Deny messages are error messages.** When a hook or permission layer blocks a call, its text is
consumed by an agent, and a bare "blocked" produces either a retry loop or silent abandonment. Every
denial is one of two cases — say which:

- **CASE A — redirect.** The *goal* is fine; the *route* is wrong. Name the approved route:
  "Direct DB writes are blocked — apply schema changes via a migration file."
- **CASE B — policy denial.** The goal itself is out of bounds. Say so, name the policy, and tell the
  agent to stop rather than route around: "Force-push to a shared branch is not permitted (branch
  protection). Do not retry; ask a human if you believe this is wrong."

> Error-envelope discipline (categories, hints, exit codes from category, the `code == 0` trap)
> adapted (stack-agnostic) from the MIT-licensed [`larksuite/cli`](https://github.com/larksuite/cli).
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
7. **Anchor edits to content** — hash at read, re-verify at apply, fail fast on drift; a byte-identical
   edit means "the bug is elsewhere", and repeated no-ops are a hard error (§9).
8. **The description is a prompt** — surface not machinery, six-part anatomy, prune only on evidence
   (§10).
9. **Errors carry category + hint** — split envelope, wire-stable category IDs, exact recovery
   command; deny messages state CASE A (redirect: name the approved route) or CASE B (policy: stop,
   don't route around) (§11).

## Relationship to other rules

- **`.claude/rules/agent-guardrails.md`** — tools as privilege boundary; least privilege; gating.
- **`.claude/rules/mandatory-workflow.md`** — the parallel-lane model that §7's Brooks's-law caution
  applies to, and the durable cross-turn state §8 calls for.
- **`.claude/rules/continuity.md`** — durable workflow state across turns/handoffs (§8).
- **`.claude/rules/reasoning-techniques.md`** / **`model-tiers.md`** — tool use is part of how an agent reasons.
- **`.claude/rules/evals.md`** — measure whether a tool change actually helps.
- **`catalog/mcp.yaml`** (kit authors) — where MCP servers are declared and wired into a project.
