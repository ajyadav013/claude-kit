---
source: https://redis.io/blog/prompt-caching-vs-semantic-caching/
author: Jen Agarwal (Redis)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Prompt caching reuses context, semantic caching reuses answers — run both

## What it teaches
An LLM-backed agent burns money and latency in two distinct places, and each
needs its own cache. The first is the input side: every call re-feeds the same
large fixed context (a long document, a system prompt, a tool catalogue, the
accumulated turns of a conversation) and the model re-processes those tokens
from scratch. Prompt caching stores the already-processed prefix so a later
request carrying the same leading context skips the recomputation. The second
is the output side: distinct users phrase the same intent differently, and an
exact-match key/value cache treats those as unrelated misses. Semantic caching
stores past query-answer pairs keyed by embedding, and serves a stored answer
when a new query is close enough in vector space — eliminating the model call
entirely rather than merely making it cheaper. The two are orthogonal, they
compose, and the piece frames running both ("double caching") as the default
posture for any nontrivial agent.

## Key patterns & decisions
- **Two caches, two units of reuse** — prompt caching's unit is the prompt
  prefix (tokens already processed); semantic caching's unit is the
  query-response pair (meaning already answered). Confusing them leads to
  building one and assuming the other's benefit.
- **Match semantics differ fundamentally** — prompt caching hits on exact or
  prefix match, so it is deterministic and cheap to reason about. Semantic
  caching hits on similarity search over embeddings, so a threshold is a
  tunable correctness knob, not just a performance knob.
- **Prompt caching preserves the model call; semantic caching removes it** —
  a prompt-cache hit still runs inference (you saved context processing). A
  semantic-cache hit returns a stored answer with no LLM in the loop, which is
  why the reported savings are much larger and the correctness risk is too.
- **Agentic loops multiply the input waste** — the piece notes that in a
  multi-step agent flow the same big context is re-processed at every step,
  so the prompt-caching win scales with the number of steps in the loop, not
  just the number of user requests.
- **Lifetime and invalidation are asymmetric** — prompt caches are short-lived
  and time-bounded (the article cites 5-60 minutes for Anthropic) and miss
  automatically when the context changes or the TTL expires. Semantic caches
  are governed by configurable TTL plus eviction plus the similarity
  threshold, so staleness is an explicit design decision you own.
- **Integration cost is asymmetric too** — the article characterises prompt
  caching as low effort (prefix tagging with Anthropic, automatic with
  OpenAI), while semantic caching requires an embedding model plus a vector
  store, or a managed service that hides them.
- **Workload shape picks the technique** — many requests sharing one large
  fixed context (document summarisation, long-context agents) points at
  prompt caching; many differently-worded requests sharing one intent
  (chatbots, support desks, RAG and knowledge-base querying) points at
  semantic caching.
- **Claimed magnitudes** — the post asserts semantic caching can cut costs by
  up to 90% and reports roughly a 15x speedup in some workloads. These are
  vendor figures for Redis LangCache, not independently measured, and should
  be treated as an upper bound to verify against your own traffic.
- **Consistency is a side effect worth naming** — because a cached prefix or a
  cached answer removes sampling variance for repeated inputs, caching also
  makes repeated queries answer more consistently, which matters for evals and
  for user trust.

## When to apply / trade-offs
Reach for prompt caching almost unconditionally when a stable prefix (system
prompt, tool schemas, retrieved corpus, conversation history) dominates your
token count — the effort is small, the semantics are exact-match, and there is
no new correctness risk beyond stale context if you cache something that
should have changed. Semantic caching is a much bigger commitment: you are
choosing to answer some fraction of requests without consulting the model, so
a badly tuned similarity threshold silently returns a confidently wrong answer
to a question nobody asked, and a cached response can outlive the fact it
asserts. Avoid it where answers are user-specific, permission-scoped,
time-sensitive, or personalised — a multi-tenant agent must key the cache by
tenant or it will leak one customer's answer to another. Also avoid it where
the value of the product is a fresh, individualised response. The embedding
call and vector lookup are not free either, so on low-volume or highly diverse
traffic the cache tax can exceed the savings. Treat cache-hit rate and
false-hit rate as first-class monitored metrics, not as install-and-forget
infrastructure.

## Fidelity check
1. Claim: prompt caching stores already-processed tokens for a repeated
   context, illustrated with a long-document example. Support: the capture
   describes saving a previously processed prompt so the model reuses it
   instead of recomputing, using a 200-page document summarisation scenario
   and noting the agentic flow compounds the problem at every step.
2. Claim: semantic caching matches on meaning via embeddings and can serve a
   stored answer to a differently-worded query. Support: the capture defines
   semantic caching as matching on semantic meaning rather than exact
   key-value lookup, stores query-answer pairs via vector embeddings, and
   gives the password-reset versus cannot-log-in example as a hit.
3. Claim: the recommended posture for complex systems is to run both caches
   together. Support: the capture has a section arguing for "double caching",
   with a customer-support agent example where the prompt cache avoids
   reprocessing the knowledge base and the semantic cache collapses
   equivalent password questions onto one answer.
