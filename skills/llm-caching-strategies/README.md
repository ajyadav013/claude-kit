# llm-caching-strategies

Caching patterns specific to LLM applications — provider prompt/prefix caching, semantic response caching, and the correctness controls each one needs.

## What this covers

This skill encodes the decisions behind LLM-specific caching:

- **Naming the layer** — four things get called the cache (exact response, semantic response, provider prompt/context, runtime KV/prefix) and each carries a different win, risk, and owner; the two response layers are the only ones that avoid running the model at all
- **Prompt-layout discipline** — ordering request blocks most-stable-first so the reusable prefix actually extends, and the prefix contaminants (timestamps, session IDs, unstable serialization) that silently destroy it
- **Break-even arithmetic** — cache-write premiums mean prompt caching is a decision with a threshold, not a free win; how to model blended cost against expected hit rate
- **Similarity thresholds as a correctness knob** — deriving a threshold per answer class from labelled near-duplicates and adversarial near-misses, and why published numbers are not portable across embedding models
- **Scope gates** — tenant, permission boundary, locale, product version, source hash, answer class, and freshness must all match before a semantic hit is served; similarity alone never authorizes one
- **What must never be cached** — authorization-dependent, account-specific, volatile-truth, and personalised responses
- **Invalidation with provenance** — TTL with jitter, proactive purge by source or policy version, preload/refresh, and an operator kill switch
- **Placement** — shared LLM gateway versus per-service caches, and the storage ladder from process memory to a distributed vector store
- **Measurement** — safe hit rate and sampled false-hit rate rather than hit rate alone, plus cached-token metrics and correction signals
- **Shadow rollout** — evaluating cache decisions against live traffic before any hit reaches a user

## Derived from published engineering writing

The patterns are distilled from a cluster of practitioner and vendor articles on LLM caching, captured as attributed own-words digests under `references/`. Vendor-reported figures (savings percentages, break-even ratios, minimum prefix lengths) are carried through as shape-of-the-problem inputs to verify against your own traffic and current pricing, not as budget numbers.

## Structure

- `SKILL.md` — full pattern guide with usage triggers, core conventions, workload-shaped defaults, and anti-patterns
- `references/aie-054-prompt-caching-vs-semantic-caching-how-to-make-ai-agents-f.md` — the two units of reuse (prefix vs query-answer pair) and why the caches compose
- `references/aie-055-the-cache-has-layers-prompt-caching-semantic-caching-and-w.md` — the four cache layers, scope gates beyond similarity, asymmetric cost of false hits
- `references/aie-056-prompt-caching-cut-llm-costs-keep-quality.md` — write premium, blended-cost model, hierarchical invalidation and block ordering
- `references/aie-057-semantic-caching-boost-llm-speed-and-reduce-costs.md` — gateway placement, shared hit rate, agentic and GPU-constrained demand profiles
- `references/aie-058-optimize-llm-response-costs-and-latency-with-effective-cac.md` — adoption heuristic, TTL jitter, context segregation, PII screening behind the cache

## Usage

Reference this skill when:

- An LLM feature's token spend or p95 latency needs to come down
- Choosing between prompt caching and semantic caching, or scoping both
- Reviewing a proposed semantic cache on a multi-tenant, permission-scoped, or regulated surface
- A prompt cache reports a low hit rate despite an apparently stable prompt
- Investigating a report that the assistant answered a question the user did not ask
- Designing invalidation, provenance, and operator purge tooling for cached answers

## Cross-references

- **redis-caching-patterns** — the cache substrate. Client lifecycle, tenant key namespacing, TTL configuration, SCAN-based invalidation, stampede protection, eviction and persistence. Use it for how the cache works; use this skill for what is safe to put in it.
- **multi-tenancy-patterns** — tenant isolation and context propagation, which the semantic cache's scope gates depend on.
- **langfuse-llm-tracing** — recording cache hits, misses, and gate failures on the same trace as the generation they replaced.
- **performance-optimization** — latency budgets and the other levers (prompt shortening, streaming, model routing) that may beat caching outright on low-volume traffic.

## Key difference from conventional caching

A conventional cache is exact-match, so a lookup either finds the right value or finds nothing. A semantic cache matches on approximate meaning, which introduces a failure mode conventional caching does not have: it can return a plausible, fluent answer to a question that was never asked, with no error and no signal to the user.

- **Prompt/prefix cache** → provider-side, exact prefix match, deterministic, cheap to reason about; worst case is stale context. Reduces cost, never removes the model call.
- **Semantic response cache** → application-side, approximate match, tunable threshold; worst case is a confidently wrong answer or a cross-tenant leak. Removes the model call entirely, which is why the savings and the risk are both much larger.

That asymmetry is the reason prompt caching is close to a default and semantic caching is a product decision requiring gates, shadow evaluation, sampled review, and a kill switch.
