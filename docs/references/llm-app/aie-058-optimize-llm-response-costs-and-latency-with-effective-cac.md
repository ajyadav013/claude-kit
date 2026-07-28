---
source: https://aws.amazon.com/blogs/database/optimize-llm-response-costs-and-latency-with-effective-caching/
author: Hanish Garg, Mike Kuentz and Parnab Basak (AWS Database Blog)
license-note: ideas absorbed in own words; no text or code reproduced
---

# An LLM cache is durable storage on the request path, not just a hit-rate target

## What it adds beyond the primary

The primary explains *what* prompt caching and semantic caching each reuse;
this post supplies the operational rules for running one in production, which
the primary largely omits. Four are concrete and new. First, an adoption
heuristic: if a cache cannot serve at least 60% of calls, the added
architecture is probably not worth its complexity, and prompt shortening or
response streaming is the better lever. Second, TTL jitter — adding a small
random offset to each entry's expiry so a popular set of cached answers does
not expire in lockstep and dump a synchronized burst of inference requests on
the model, which can trip provider throttling (the same herd argument the kit
already makes for CDN TTLs, now pointed at an inference backend). Third,
context-specific segregation: the same question can have different correct
answers per domain or tenant, so cache entries need distinct namespaces,
indices or partitions or a hit silently leaks one context's answer into
another. Fourth, guardrails matter *more* behind a cache than in front of one,
because a cache turns a transient prompt and response into persisted data —
so both the stored query and the stored answer must be screened for PII before
they are written. It also frames invalidation as three separable strategies
(TTL expiry, proactive deletion of specific entries when the knowledge base is
corrected, and preload/batch refresh when new source data lands), lays out a
storage ladder from process-local memory (dev only; unshareable across
processes) through a local file database to an external distributed store, and
argues these layers compose rather than compete. Vendor-specific figures given:
prompt caching on Bedrock claimed to cut response latency by up to 85% and
input token cost by up to 90%.

## Primary source for this cluster

[aie-054-prompt-caching-vs-semantic-caching-how-to-make-ai-agents-f.md](aie-054-prompt-caching-vs-semantic-caching-how-to-make-ai-agents-f.md)

## Fidelity check

1. Claim: a cache serving under 60% of system calls may not repay its
   complexity, with prompt optimization or streaming as alternatives.
   Support: the capture states this heuristic in its section on evaluating
   caching complexity and names those two alternatives.
