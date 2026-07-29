---
source: https://acethecloud.com/blog/prompt-caching-semantic-caching-tradeoffs/
author: Abhishek Kumar (Ace The Cloud)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Four things are called cache; only the response layers skip the model call

## What it teaches
LLM caching is not one feature; it is at least four distinct layers that get
conflated because they share a word. An exact response cache keys on a
normalized request and is the cheapest, safest hit but covers little traffic.
A semantic response cache matches on intent via embedding similarity and is
where the real money is, because it can eliminate the generation entirely —
and where the real risk is, because a false hit returns a confidently wrong
answer. A prompt/context cache reuses an already-processed input prefix at
the provider, cutting input-token cost and latency but still paying for
generation. A KV/prefix cache reuses internal attention state inside the
serving runtime, speeding prefill and creating routing locality, at the cost
of memory pressure and tenant-boundary concerns. The correct architecture
layers all four rather than choosing one, and the semantic layer must be
gated by scope predicates and treated as product policy, not ML tuning.

## Key patterns & decisions
- **Four layers, four failure modes** — exact response cache (risk: low
  coverage), semantic response cache (risk: false positive / stale answer),
  prompt or context cache (risk: output still generated, so savings are
  input-side only), KV/prefix cache (risk: memory pressure and tenant
  leakage). Naming which one you mean is the precondition for reasoning
  about any of them.
- **Only response caches skip the model** — prompt and KV caching optimize
  the generation path that still runs. If the same support question arrives
  ten thousand times, prompt caching trims the input side while semantic
  response caching removes the call altogether. Conflating the two produces
  wildly wrong cost projections.
- **Prompt order is a cost lever** — reusable prefixes only extend as far as
  the first volatile token. Put system instructions, tool schemas, and stable
  policy context first; retrieved documents next; the user question last. A
  semantically identical layout that leads with user text or session noise
  destroys prefix reuse.
- **Semantic hits need gates, not just a similarity number** — a cosine score
  is insufficient. The hit must also match on tenant or public scope, locale,
  product/version, permission boundary, source document version, and answer
  type, and must still be within freshness, with no policy override active.
  Any gate failure should force a miss.
- **Asymmetric cost of errors** — a false miss costs tokens; a false hit costs
  credibility. This asymmetry is the whole argument for starting with a
  conservative threshold and loosening only with evidence.
- **The threshold is a per-answer-class product decision** — lower thresholds
  buy hit rate and savings while raising false-positive risk; higher
  thresholds do the reverse. A refund policy and a keyboard shortcut should
  not share a threshold.
- **Shadow before serving** — evaluate semantic cache decisions offline
  against live traffic, track user corrections, and sample hits for human
  review before any hit is actually returned to a user.
- **Cache with provenance and a purge path** — store source hashes and policy
  versions alongside each cached response, and give operators purge/refresh
  by canonical intent, source document, tenant, and policy version.
- **Instrument cached tokens separately** — cached input tokens should be a
  distinct metric from ordinary input tokens, alongside safe hit rate, false
  positives, stale-hit blocks, and cost avoided. Hit rate alone is a
  misleading success metric.
- **Workload-shaped defaults** — repeated tool schemas: prompt cache yes,
  semantic no. FAQ/docs: both. Account-specific support: cache the
  explanation, fill live data at request time. Regulated answers: prompt
  cache yes, semantic only with high precision and strict freshness. Coding
  agents: prompt cache yes, semantic rarely on the final answer. Incident
  status: usually no semantic cache, since truth changes fast.

## When to apply / trade-offs
Apply this when an LLM feature has repeated traffic and a cost or latency
problem — high-volume support, docs Q&A, or any agent resending large static
prefixes. Prompt/context caching is close to free to adopt and mostly costs
prompt-layout discipline, so it is a reasonable default on every call.
Semantic response caching is a different commitment: it adds an embedding
model, a vector index, a gating layer, a shadow-evaluation pipeline, human
sampling, and per-intent purge tooling, and it introduces a class of failure
where the system is wrong rather than slow. Do not reach for semantic caching
on volatile-truth surfaces (incident status, live account balances, anything
where the answer's correctness has a short half-life), on low-volume
endpoints where the machinery costs more than it saves, or before you can
measure false-positive rate. The article's framing of the best cache as the
one that saves money without making users suspicious is the right acceptance
criterion — optimizing hit rate in isolation optimizes the wrong thing.

## Fidelity check
1. Claim: there are four commonly-conflated cache layers with distinct wins
   and risks. Support: the capture contains a table listing exact response
   cache, semantic response cache, prompt/context cache, and KV/prefix cache
   with a "main win" and "main risk" column for each, including "low
   coverage", "false positive, stale answer", "still generates output", and
   "memory pressure, tenant boundaries".
2. Claim: prompt caching reduces input cost but the model still generates.
   Support: the capture states the model still generates output and contrasts
   the ten-thousand-repeat support question, where prompt caching reduces the
   input side while semantic response caching can avoid generation entirely.
3. Claim: semantic hits require gates beyond similarity. Support: the capture
   explicitly rejects relying on a cosine similarity of 0.91 and enumerates
   required conditions — same tenant or public scope, locale, product/version,
   permission boundary, source document version, answer type, freshness still
   valid, no policy override.
