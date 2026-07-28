---
source: https://redis.io/blog/context-engineering-vs-prompt-engineering/
author: Jim Allen Wallace (Redis)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Agent answers fail in the context-assembly layer, not in the prompt

## What it teaches
A prompt is fixed at build time; an agent's context window is rebuilt on every
call by code that runs immediately before inference — retrieving documents,
loading a slice of memory, attaching tool definitions, and trimming what will
not fit. Because of that split, most production agent failures are structural
rather than lexical: the retrieval hit a store that only syncs overnight, the
tool set was too wide to choose from, or nothing carried over between turns.
Rewriting the system message cannot reach any of those. The piece reframes
prompt engineering as one input inside context engineering (not a peer
discipline), splits the window into three buckets that fill for different
reasons, and argues that the two dominant context defects — staleness and
fragmentation across systems — are data-infrastructure problems solved in the
assembly layer, at concurrency and latency budgets, not at the model.

## Key patterns & decisions
- **Prompt engineering is a subset, not a sibling** — prompting governs *how*
  you instruct the model for one call; context engineering governs *what the
  model knows* when it answers across many calls and tool invocations. Treating
  them as alternatives is what produces the rewrite-the-prompt reflex.
- **Three buckets in every context window** — instructions (system message,
  few-shot examples, tool descriptions), knowledge (facts the model was not
  trained on, including RAG results), and tools (function/API/MCP server
  definitions). The model reasons over these and literally nothing else — not
  the previous request, not a record that changed after assembly.
- **Design-time vs runtime is the load-bearing distinction** — a prompt is
  frozen when written, so it cannot retrieve, cannot remember, and cannot
  prune. Only the assembly step reaches live sources (vector stores, APIs,
  memory) and it must do so inside the agent's latency budget.
- **Prompt tuning does not survive its dependencies** — it overfits the
  phrasings in your test set while real users paraphrase endlessly, it breaks
  when a tool schema or column order changes, and it decays across model
  version bumps. Each of those is a structural weakness wearing a wording
  costume.
- **Three recurring context failures** — bloated tool sets (too wide a decision
  surface, so the agent picks wrong), missing memory (nothing persists past the
  window in multi-step or conversational work), and broken retrieval (a perfect
  prompt cannot compensate for an incomplete pipeline).
- **Freshness is an agent-specific requirement** — most data stacks were built
  for human consumers on batch/daily refresh cadence. In an observe-decide-act
  loop, a second observation that returns outdated state makes the agent
  re-plan and burn tokens; acting on stale inventory is a business risk, not a
  quality nit.
- **Fragmentation is a consistency problem, not a plumbing chore** — customer
  records, policies, and fast-moving operational data sit in separate APIs,
  databases, and SaaS tools. Pulling them into one coherent window quickly, for
  thousands of concurrent users, is a concurrency/consistency/durability
  problem.
- **Semantic caching as a cost and tail-latency lever** — match an incoming
  query against prior ones by embedding similarity rather than exact string
  equality, and return the cached response without a fresh LLM call. One cited
  evaluation reported up to a 68.8% reduction in API calls across tested query
  categories.
- **Consolidate memory and retrieval on one layer** — they depend on each
  other, so splitting them across stores invites dual-write failures and drift.
  The named engine responsibilities are cross-session/cross-agent memory, task
  routing, tool boundary enforcement, token budget management with automatic
  pruning, and consistency so one agent's decision is visible to the others.

## When to apply / trade-offs
Apply this framing the moment an agent works in a demo and degrades in
production, and specifically before a third round of prompt rewrites for the
same class of failure — the diagnostic question shifts from how to word the
request better to what the model must know at this point in the task. It costs
real systems work: an assembly layer with retrieval, memory consolidation
rules, caching, and freshness guarantees is closer to distributed-systems
engineering than to prompt writing, and it introduces its own failure surface
(cache staleness, consolidation bugs, latency added before every inference). It
is overkill for genuinely single-turn bounded tasks where everything needed
fits in one well-worded request — prompting earned its reputation there and
still works. Note the source is vendor content: the diagnosis (assembly layer,
three buckets, freshness vs fragmentation) generalises, but its conclusion that
a single consolidated platform beats separately assembled stores is a product
argument, and the 68.8% figure is a single cited evaluation, not a benchmark
you should carry into your own capacity planning.

## Fidelity check
1. Claim: prompt engineering is a piece of context engineering rather than the
   reverse. Support: the capture states this ordering explicitly and draws the
   line as instruct-the-model versus what-the-model-knows-when-it-answers.
2. Claim: the context window splits into instructions, knowledge, and tools.
   Support: the capture enumerates exactly these three buckets, listing
   system messages and few-shot examples under instructions, RAG results under
   knowledge, and APIs plus MCP servers under tools.
3. Claim: semantic caching reduced API calls by up to 68.8%. Support: the
   capture attributes that figure to one evaluation across tested query
   categories, in the passage describing embedding-similarity matching versus
   exact string matching.
