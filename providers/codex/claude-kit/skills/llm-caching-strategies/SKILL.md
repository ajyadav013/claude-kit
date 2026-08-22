---
name: llm-caching-strategies
description: Caching for LLM applications — provider prompt/prefix caching, semantic response caching, similarity thresholds, scope gates, invalidation. Use when cutting LLM cost or latency. Distinct from redis-caching-patterns key-value caching.
---

# LLM Caching Strategies

An LLM application does not have "a cache" — it has several, they reuse different things, and they fail in different ways. Prompt/prefix caching is provider-side, matches exactly on a leading span of the request, and can only ever make a call cheaper. Semantic caching is application-side, matches *approximately* on meaning, and skips the model call entirely — which is where the savings are and where the risk of confidently answering the wrong question lives. This skill covers how to pick, key, gate, invalidate, and measure each layer. For conventional key-value caching mechanics (Redis clients, namespacing, SCAN invalidation, stampede protection, eviction policy) use `redis-caching-patterns`; this skill assumes that substrate and stays on the LLM-specific concerns.

## When to use

- Adding caching to an LLM feature whose token bill or p95 latency has become a problem
- Deciding between prompt caching and semantic caching, or working out whether to run both
- Restructuring a prompt so a stable prefix is actually reusable across requests
- Choosing and defending a similarity threshold for a semantic cache
- Reviewing a proposed semantic cache on a multi-tenant, permission-scoped, or regulated surface
- Diagnosing a prompt cache that reports a surprisingly low hit rate despite a "stable" system prompt
- Investigating a report that the assistant answered a question the user did not ask
- Designing invalidation for cached answers when the underlying knowledge base or policy changes
- Deciding where the cache lives — inside each service, or in a shared LLM gateway
- Building the metrics and alerts for a cache that is already in production
- Estimating whether a cache will pay for itself before building it

## Core conventions

### Name the layer before you tune it

Four distinct things get called "the cache". Say which one you mean in the design doc, because the win, the risk, and the owner differ:

| Layer | Reuses | Saves | Primary failure |
|---|---|---|---|
| Exact response cache | Normalized request → stored answer | The whole call | Covers very little real traffic |
| Semantic response cache | Similar intent → stored answer | The whole call | False hit — wrong or stale answer served confidently |
| Prompt / context cache | Already-processed input prefix (provider-side) | Input tokens and prefill latency | Output is still generated, so savings cap out on the input side |
| KV / prefix cache | Attention state inside the serving runtime | Prefill work, routing locality | Memory pressure; tenant boundaries inside a shared runtime |

These compose. A well-built system runs an exact cache in front of a semantic cache in front of a prompt-cached model call. Confusing them produces cost projections wrong by an order of magnitude. Take one support question that shows up ten thousand times: with prompt caching you pay for ten thousand generations, each somewhat cheaper on its input side. With a semantic response cache, only the first one runs at all.

The KV/prefix layer is only yours to tune if you operate the inference runtime. On a hosted API it is the provider's implementation detail, surfaced to you as the prompt cache.

### Prompt caching — order blocks most-stable-first

A reusable prefix extends exactly as far as the first token that changes. Everything after the first volatile byte is recomputed. So prompt layout, not prompt content, is the dominant lever on hit rate.

Order request content by descending stability:

1. Tool and function definitions
2. System instructions and policy text
3. Retrieved documents and reference corpora
4. Conversation history
5. Per-request working memory, dynamic state, and the live user question — always last

Invalidation is hierarchical: change a block and you invalidate it plus everything after it. A prompt that leads with a timestamp has no cacheable prefix at all, no matter how stable the following 40k tokens are.

The recurring cache killers are all prefix contaminants, and all of them look harmless in review:

- A generated timestamp or "today's date" line in the system prompt
- Session IDs, request IDs, usernames, or trace IDs interpolated into the preamble
- Non-deterministic serialization — a dict whose key order varies, a JSON dump with unstable spacing, trailing-whitespace or casing drift between call sites
- Per-request working memory or scratchpad state parked in the system block "because it is context"

Relocating per-request scratch state from the system block down to a trailing user turn is usually the highest-leverage single fix available. One published case reports a hit rate climbing from roughly 7% to 84% on that change alone, with overall spend down about 59%. Treat that as the shape of the win, not a promise.

Two practical constraints to check against your provider's current documentation rather than memory: there is a **minimum cacheable prefix length** (on the order of a thousand-plus tokens for larger models, several thousand for the small ones — below that the provider simply will not cache), and a **cap on the number of cache breakpoints** per request (a small single-digit number). Place breakpoints deliberately at the boundaries you listed above; do not sprinkle them.

Do not reflexively wrap the cache boundary around the entire context. There is published evidence that indiscriminately caching everything can make latency *worse*, because the bookkeeping outweighs the reuse once the tail of the context turns over on every call. Put the boundary where the content is genuinely stable and nowhere else.

### Prompt caching has a break-even, so compute it

Prompt caching is not free. Providers differ, but the shape is: a cache **read** costs a fraction of the base input rate (on the order of a tenth), while populating an entry may cost a **write premium** above base input — materially so for longer-lived cache tiers, and not at all on providers that cache implicitly.

Model the blended cost relative to base input as:

```
blended = (1 - hitRate) * writeMultiplier + hitRate * readMultiplier
```

Two consequences worth putting in the design doc:

- Where a write premium exists, a short-TTL tier only pays for itself above roughly 1.4 reads per write. Below about a 30% hit rate you may be paying *more* than not caching.
- A prompt you believe is stable that is not clearing a high hit rate is telling you about a structural problem in prompt layout, not about the cache. Investigate the prefix before tuning anything else.

Because the write is a real cost, the traffic pattern matters as much as the prompt: a stable prefix touched once an hour against a five-minute TTL never reads its own write. Move to a longer-lived tier, batch the traffic, or do not cache. Where the provider supports it, you can **pre-warm** an entry ahead of a known burst — send one request that generates almost no output, then check the usage payload to confirm the entry was actually written before the traffic arrives.

Rates change frequently. Re-derive the break-even from current pricing at design time; never hard-code a multiplier into a runbook.

### Semantic caching — the threshold is a correctness control

A semantic cache embeds the incoming query, does a nearest-neighbour lookup against previously answered queries, and — if the best match clears a similarity threshold — returns the stored answer without consulting the model. That last clause is the entire risk. You are electing to answer some share of user questions out of a lookup table indexed by approximate meaning.

The error costs are asymmetric and this asymmetry should drive every decision below:

- A **false miss** costs tokens and latency. It is invisible to the user.
- A **false hit** answers a question the user did not ask, fluently and with no hedging. It costs credibility, and in a regulated or account-specific context it can cost more than that.

So: start conservative, loosen only against evidence.

### Picking a threshold, concretely

Do not adopt a number from a blog post. Cosine scores are not comparable across embedding models, across versions of the same model, or across domains — a 0.92 that is a safe hit in one corpus is a false hit in another. Derive it:

1. Assemble a labelled set of query pairs from real traffic — near-duplicates that *should* share an answer, and adversarial near-misses that must not. Near-misses are the valuable half and the half teams skip. Harvest them from the domain's own vocabulary traps — negations ("how do I enable X" vs "how do I disable X"), quantity and plan tiers, product versions, and entity swaps.
2. Sweep the threshold across the labelled set and plot false-hit rate against hit rate.
3. Pick the **highest** threshold that still delivers useful coverage at a false-hit rate your product can defend, per answer class.
4. Re-derive whenever the embedding model, its version, the chunking, or the domain changes. Changing the embedder invalidates both the index and the threshold.

**Thresholds are per answer class, not global.** A keyboard-shortcut question and a refund-eligibility question should not share a number. Model this explicitly: attach an answer class to each cached entry, and let each class carry its own threshold, TTL, and whether it is cacheable at all.

Also budget for the cache's own cost. Every miss now pays an embedding call plus a vector search before it pays for the model. On low-volume or highly heterogeneous traffic that tax exceeds the savings. A useful adoption heuristic: unless you expect the cache to serve a clear majority of calls — around 60% is the commonly cited floor — the machinery rarely repays what it costs to build and operate, and you will buy more perceived speed for less operational surface by trimming the prompt or streaming the response.

### Similarity is necessary, never sufficient — gate every hit

A vector score alone must not authorize a hit. Attach structured metadata to each entry and require an exact match on every gate before the answer is served. Any gate that fails or is unknown forces a miss:

- **Tenant or explicit public scope** — the non-negotiable one. Without it, one customer's answer is served to another.
- **Identity and permission boundary** — the effective role or entitlement set that produced the answer. An answer generated for an admin must never surface to a viewer.
- **Locale and language**
- **Product, plan tier, and version** — the same question has different correct answers per release
- **Source document version or content hash** — so a corrected knowledge base does not keep serving the old answer
- **Answer class** — as above; also prevents a short factual answer being served where a long-form explanation was requested
- **Freshness** — the entry is inside its TTL for its class
- **No active policy override** — a kill switch that forces misses for a class, tenant, or intent

Encode these in the cache key or as filter predicates on the vector query, not as a post-hoc check that a future refactor can drop. The key design that holds up is: **a partition per hard boundary (tenant, locale, product version), similarity search only within the partition, and metadata gates on the candidate before returning it.** Never rely on the embedding to encode a tenant ID — it will not, and semantically identical questions from different tenants will collide by design.

### What must never be reused across requests

Some responses should not enter a shared semantic cache under any threshold:

- Anything that names or reflects a specific user, account, balance, order, or entitlement
- Anything whose correctness depends on the caller's authorization — cache the *explanation*, look up the account-specific numbers live at request time and compose the two
- Volatile-truth surfaces — incident and system status, availability, pricing during a change window, anything with a short correctness half-life
- Personalised output where individualisation *is* the product
- Non-deterministic or creative generation, where two callers receiving the same text is itself the defect
- Free-text queries not yet screened for PII — see below

Caching promotes a throwaway exchange into **stored data**, and storage changes its compliance posture. PII screening and redaction therefore carry more weight on the write path into the cache than on the display path out of the model — apply them to the query text and the answer text alike, before either is committed, not only when something is rendered. Retention limits, deletion-request handling, and encryption-at-rest obligations now attach to your cache store. Coordinate the tenant-boundary side of this with `multi-tenancy-patterns`.

### Invalidation, TTL, and provenance

Treat cached answers as derived data with a traceable lineage. Store alongside each entry: the source document IDs and content hashes, the prompt/policy version, the model and embedding-model identifiers, the answer class, and the creation timestamp. Without provenance you cannot purge selectively and will be forced into a full flush every time a document changes.

Three separable invalidation strategies, all of which you will eventually need:

1. **TTL expiry** — the baseline, set per answer class rather than globally. Add **jitter** to each expiry so a popular cohort does not all fall due at the same instant and fire one simultaneous wave of regeneration at the model, which is exactly how you trip a provider rate limit. This is the thundering-herd problem `redis-caching-patterns` already covers for conventional caches; the origin being protected here is an inference backend with a hard quota, so the consequence of getting it wrong is throttling rather than merely load.
2. **Proactive deletion** — when a source document is corrected or a policy changes, purge by source hash, by policy version, by canonical intent, or by tenant. Build these purge paths as operator tooling on day one, not after the first incident.
3. **Preload / batch refresh** — when a new corpus or policy version ships, regenerate the top-N known intents before traffic arrives, so the cache is already warm and the herd never forms.

Ship a **kill switch** that disables semantic hits per class, per tenant, or globally without a deploy. When an incorrect answer is reported, the first action is to stop serving it; root cause comes second.

### Where the cache lives

Prompt caching is inherently provider-side; your only decision is prompt layout and cache-breakpoint placement.

For the semantic layer, prefer a **shared LLM gateway** in the request path over per-service implementations. The hit rate compounds as more services route through one cache, thresholds and TTLs are tuned centrally, scope and opt-in/opt-out become per-route configuration rather than code, and savings are attributable back to the calling application. The cost is a new component in the hot path and a shared blast radius — which is precisely why the per-route opt-out and the kill switch above are load-bearing.

For the store itself, there is a ladder and the rungs compose rather than compete: process-local memory (development only — unshareable across processes and lost on restart), a local embedded database, then an external distributed store with vector search. Anything multi-process or multi-instance needs the external tier; see `redis-caching-patterns` for the operational mechanics.

### Measure safe hits, not hits

Hit rate on its own will mislead you, because the cheapest way to raise it is to lower the threshold — which is also the cheapest way to start being wrong. Instrument:

- **Safe hit rate** — hits that survived all gates and were not subsequently corrected
- **False-hit rate** — sampled and human-labelled, per answer class. If you cannot produce this number, you do not know whether the cache is working
- **Downstream correction signals** — user rephrases immediately after a cached answer, thumbs-down, escalation to a human, retry within the session. A rephrase-after-hit spike is the classic signature of a threshold set too low
- **Stale-hit blocks** — gate failures by gate type; a spike in source-version blocks means your invalidation is lagging
- **Cached input tokens as a distinct metric from ordinary input tokens** — providers report these separately in the usage payload, so prompt-cache hit rate is a first-class observable that should alert on regression rather than something you discover on the invoice
- **Cost avoided and latency saved**, split by layer, so you can tell whether the prompt cache or the semantic cache is carrying the result
- **Threshold distribution** — the histogram of best-match scores, including near-misses just under the threshold. This is what tells you whether a proposed threshold change is safe

Wire these through your existing LLM tracing so cache decisions appear on the same trace as the generation they replaced — see `langfuse-llm-tracing`. A cached response with no trace is an invisible answer.

### Roll out in shadow mode

Never enable semantic hits directly into production traffic. Run the cache in **shadow**: compute the lookup, record what it *would* have returned, call the model anyway, and compare. Score the shadow hits offline against the live answers, sample them for human review, and only then serve — one answer class at a time, starting with the most tolerant class, with the kill switch already wired.

The acceptance criterion is not a hit rate. It is that the cache saves money **without users noticing it exists**. If they can tell, the threshold is wrong.

### Workload-shaped defaults

A starting posture, to be argued with rather than adopted blindly:

| Workload | Prompt cache | Semantic cache |
|---|---|---|
| Repeated tool schemas and long system prompts | Yes, always | No |
| Public docs and FAQ Q&A | Yes | Yes — the best case for it |
| Long-document analysis, multi-step agent loops | Yes — the win multiplies per step | Only on stable sub-questions |
| Account-specific support | Yes | Cache the generic explanation only; fill live data at request time |
| Regulated or compliance answers | Yes | Only with a high-precision threshold, strict freshness, and audit |
| Coding agents | Yes | Rarely on the final answer; the context is too caller-specific |
| Incident and system status | Yes | No — truth changes faster than any TTL |
| Creative or personalised generation | Yes | No — sameness is the defect |

Two demand profiles worth noting because they are routinely underweighted. In **agentic multi-step systems** the same large context is re-processed at every step and agents rephrase the same sub-question across runs, so both layers pay off harder than the request count suggests. In **on-prem or GPU-constrained deployments** the cache is not shaving an API bill at all — it is stretching fixed inference capacity, which changes the business case entirely.

## Anti-patterns to avoid

- **Saying "we added caching" without naming the layer** — prompt caching and semantic caching have different owners, costs, risks, and metrics. An unnamed cache in a design doc is an unreviewed one.
- **Projecting semantic-cache savings from a prompt cache (or the reverse)** — one trims input tokens on a call that still runs; the other removes the call. The numbers differ by an order of magnitude in both directions.
- **A timestamp, session ID, or request ID in the system prompt** — silently destroys prefix reuse for the entire remainder of the request. Check the serialized bytes, not the template.
- **Non-deterministic prompt serialization** — unordered dict keys or drifting whitespace between call sites produce a fresh prefix each time. The prompt "is the same"; the bytes are not.
- **Enabling prompt caching without checking the break-even** — where a write premium exists, low-traffic or short-lived prefixes cost more cached than uncached.
- **Wrapping the cache boundary around the whole context** — naive whole-context caching can measurably increase latency. Place the boundary where the content is actually stable.
- **Adopting a similarity threshold from a blog post** — scores are not portable across embedding models, versions, or domains. Derive it from your own labelled pairs.
- **Tuning the threshold on positive examples only** — without adversarial near-misses (negations, version swaps, plan tiers) you are measuring recall and calling it precision.
- **Treating similarity as sufficient** — a high cosine score with no tenant, permission, locale, version, or freshness gate is how one customer's answer gets served to another.
- **Assuming the embedding encodes the tenant** — it does not. Semantically identical questions from different tenants collide by construction. Partition the index.
- **Caching authorization-dependent answers** — an answer generated under one permission set must never be reused under another. Cache the explanation, fetch the entitlements live.
- **Semantic caching volatile truth** — incident status, balances, availability. The cache will be confidently wrong for exactly the duration of the TTL you chose.
- **Writing to the cache before PII screening** — the cache turns a transient exchange into persisted data with retention and deletion obligations. Screen the stored query and the stored answer at write time.
- **Optimizing hit rate as the goal** — the trivially optimal strategy is to lower the threshold until everything hits. Track safe hit rate and sampled false-hit rate together, or you are optimizing for being wrong faster.
- **No provenance on cached entries** — without source hashes and policy versions your only invalidation tool is a full flush, and you will avoid using it.
- **Unjittered TTLs** — a popular cohort expiring in lockstep dumps a synchronized burst on the inference backend and trips provider throttling.
- **No kill switch** — when a bad answer is reported you need to stop serving it in seconds, not at the next deploy.
- **Serving semantic hits before a shadow evaluation** — the first false hit should be found by your sampling pipeline, not by a customer.
- **Building a semantic cache for low-volume or highly diverse traffic** — below roughly a 60% expected serve rate, the embedding and lookup tax plus the operational surface outweigh the savings. Shorten the prompt or stream the response instead.
- **Duplicating conventional cache mechanics here** — client lifecycle, namespacing, SCAN-based invalidation, single-flight, and eviction policy belong to `redis-caching-patterns`. This layer only adds the LLM-specific semantics on top.

## References

- [aie-054-prompt-caching-vs-semantic-caching-how-to-make-ai-agents-f.md](references/aie-054-prompt-caching-vs-semantic-caching-how-to-make-ai-agents-f.md) — the two units of reuse, why the caches compose
- [aie-055-the-cache-has-layers-prompt-caching-semantic-caching-and-w.md](references/aie-055-the-cache-has-layers-prompt-caching-semantic-caching-and-w.md) — four cache layers, scope gates, asymmetric error cost
- [aie-056-prompt-caching-cut-llm-costs-keep-quality.md](references/aie-056-prompt-caching-cut-llm-costs-keep-quality.md) — write premium, break-even arithmetic, block ordering
- [aie-057-semantic-caching-boost-llm-speed-and-reduce-costs.md](references/aie-057-semantic-caching-boost-llm-speed-and-reduce-costs.md) — gateway placement and shared hit rate
- [aie-058-optimize-llm-response-costs-and-latency-with-effective-cac.md](references/aie-058-optimize-llm-response-costs-and-latency-with-effective-cac.md) — adoption heuristic, TTL jitter, segregation, PII behind the cache
- `redis-caching-patterns` — the cache substrate; namespacing, TTL config, invalidation, stampede protection, eviction
- `multi-tenancy-patterns` — tenant isolation and context propagation for the scope gates
- `langfuse-llm-tracing` — recording cache decisions on the same trace as the generation
- `performance-optimization` — latency budgets and where caching sits among other levers
