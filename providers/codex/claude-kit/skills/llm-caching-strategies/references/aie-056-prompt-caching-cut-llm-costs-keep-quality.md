---
source: https://www.digitalapplied.com/blog/prompt-caching-2026-cut-llm-costs-engineering-guide
author: Digital Applied Team (Digital Applied)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Prompt caching pays off only above a measured hit rate set by block order

## What it adds beyond the primary

The cluster primary frames prompt caching against semantic caching
conceptually; this piece supplies the operator's arithmetic. It gives a
cross-provider price table as of June 2026 (cache reads at 0.10x base input
on Anthropic and newer OpenAI models, roughly 75% off via Gemini implicit
caching), and — the part most teams miss — the *write premium*: Anthropic
bills 1.25x base input to populate a 5-minute-TTL entry and 2.0x for the
1-hour tier, while OpenAI and Gemini implicit caching charge no write
premium at all. From that it derives a blended-cost model, relative to base
input, of `(1 - hitRate) x writeMultiplier + hitRate x readMultiplier`,
which makes caching a decision with a break-even rather than a free win:
the Anthropic 5-minute tier pays for itself at roughly 1.4 reads per write,
and below about a 30% hit rate on a supposedly stable prompt the write
premium can exceed the read savings. It then reduces hit-rate engineering
to one ordering rule and backs it with a case study, plus minimum-prefix
thresholds (1,024 tokens for Claude Sonnet/Opus and GPT-5.5; 4,096 for
Claude Haiku 4.5; 2,048 for Gemini 2.5 Pro explicit caches) and a cap of
four cache breakpoints per Anthropic request.

The ordering rule: because invalidation is hierarchical on Anthropic — a
changed content block invalidates itself and everything after it — you sort
prompt blocks most-stable-first. Tool and function definitions top, then
system instructions, then reference/RAG documents, then conversation
history, with the live user query and any per-request working memory dead
last. The cited case (ProjectDiscovery) moved dynamic working memory out of
the system prompt into a trailing user message and went from a 7% to an 84%
hit rate, cutting overall LLM spend 59% with 9.8 billion tokens served from
cache. The named cache killers are all prefix contaminants: timestamps in
the system prompt, session IDs / usernames / request IDs, and silent
whitespace or casing drift in how the prefix is serialised. The piece also
cites Lumer et al. (arXiv 2601.06007) for the counterintuitive result that
naive whole-context caching can *increase* latency, so the cache boundary
should be placed deliberately rather than wrapped around everything.

Two operational details are worth lifting: Anthropic caches can be
pre-warmed before traffic arrives by issuing a request with a zero output
budget and confirming the cache-creation token count in the response, and
OpenAI reports cached token counts in the usage payload — which means cache
hit rate is a first-class observability metric that should alert on
regression, not a number you discover on the invoice. The article's own
caveat is that per-token rates move monthly, so any figure here is a
shape-of-the-problem input, not a budget.

## Primary source for this cluster

[aie-054-prompt-caching-vs-semantic-caching-how-to-make-ai-agents-f.md](aie-054-prompt-caching-vs-semantic-caching-how-to-make-ai-agents-f.md)

## Fidelity check

1. Claim: the Anthropic 5-minute tier breaks even near 1.4 reads per write,
   and under roughly a 30% hit rate on stable prompts the write premium can
   cost more than the reads save. Support: the capture states a break-even of
   1.4 reads for the 5-minute tier in its header stat line, and its
   key-takeaways block gives the ~30% threshold and notes that a sub-60% hit
   rate on stable prompts signals a structural problem.
