---
source: https://codewheel.ai/blog/rag-architecture-guide/
author: Matt Owens (CodeWheel AI)
license-note: ideas absorbed in own words; no text or code reproduced
---

# RAG fails in retrieval, not the model — filter by tenant before you search

## What it teaches
Most RAG defects are retrieval defects wearing an LLM costume: the model reasons
fine over whatever context it is handed, but the right chunk never arrived. The
article decomposes a production retrieval pipeline into six owned layers —
ingestion, indexing, retrieval orchestration, generation, observability, and
testing — and argues each needs an owner, alerts, and docs so drift has a blame
boundary. Two structural claims carry the piece. First, pure vector search has
three named blind spots (exact identifiers, precise jargon, and recency), which
makes hybrid vector-plus-keyword retrieval the default rather than an
optimization. Second, in multi-tenant products the tenant predicate must be
applied *before* the similarity search, not as a post-filter, because a
post-filter has already pulled another customer's embeddings into the process
where prompt manipulation can surface them. Everything downstream — fusion
weights, reranking, caching, cost — is then framed as an evaluation-driven
tuning problem with concrete numeric starting points and stop rules.

## Key patterns & decisions
- **Filter before you search, and fail closed** — Apply the tenant/ACL predicate
  inside the query to both the vector and the keyword engine, then re-validate
  each retrieved chunk against the requesting tenant before it enters the
  prompt. If tenant context is missing, abort the response rather than
  defaulting to unscoped retrieval.
- **The keyword index is the forgotten leak path** — Teams reliably remember to
  scope the vector store and forget the lexical index, which then serves the
  same cross-tenant content by another door. Whatever isolation the vector side
  uses (namespaces, row-level security, query filters) must be mirrored
  verbatim on the keyword side, and preferably layered.
- **Three failure classes justify hybrid** — Vector-only breaks on exact IDs
  (a ticket number retrieves semantically adjacent ticket numbers), on
  domain acronyms that embeddings blur together, and on recency questions
  where there is no notion of time in the vector at all. Keyword search and
  metadata date filters cover exactly those three.
- **Fusion is a chosen algorithm, not an accident** — Run both engines in
  parallel, cap each at roughly the top 20-30 hits, then merge by an explicit
  strategy: weighted score combination when the two score scales are
  comparable, reciprocal rank fusion (summing 1/(k+rank) with k around 60) when
  the scales differ or one engine returns no usable score, or a learned model
  when you have labelled click/judgement data to retrain on.
- **Weight the fusion to the corpus, then prove it offline** — Narrative
  documentation skews heavily to the vector side (about 80/20 to 90/10), mixed
  corpora carrying identifiers land near 60/40 or 50/50, and regulated or legal
  text inverts to keyword dominance (roughly 40/60 to 30/70). Pick the weights
  against a historical query set before A/B testing them live.
- **Reranking needs an explicit stop rule** — Reranking reorders the fused
  candidates with a heavier joint query-document model. The trigger to add it is
  precision@5 falling below about 80% after hybrid tuning, or genuinely
  multi-clause queries; the rule to remove it is a measured lift under about
  10%, at which point you are buying latency and per-query cost for nothing.
- **Rerankers differ by an order of magnitude in latency and cost** — Managed
  cross-encoder APIs sit around 100-300 ms and roughly $0.002-$0.01 per query;
  self-hosted rerankers run about 50-150 ms but need GPU capacity and ops;
  LLM-as-reranker reaches 300-800 ms at roughly $0.02-$0.10 per query; a learned
  fusion model over click data runs under 50 ms but needs a retraining pipeline.
  Latency budgets under about 200 ms end-to-end rule out most of these.
- **Chunking is a versioned artifact, not a constant** — Split on semantic
  boundaries such as headings and list items rather than a fixed token count,
  start near 300-600 tokens, keep ingestion idempotent, retain both raw and
  processed forms for audit, and treat a change to the chunking rules as a
  version bump that invalidates caches and forces a re-run of the eval suite.
- **Instrument retrieval as its own product surface** — Log the sanitized query,
  tenant, retrieval mode and latency, the chunk IDs and scores returned, the
  rerank decision, the guardrail verdict, and per-query cost. Dashboard
  precision/recall per tenant, latency percentiles, per-tenant token burn, and
  cross-tenant access attempts — the last of which should be a flat zero line
  that alerts on any deviation.
- **Design the degraded modes up front** — Name the behaviour when the embedding
  service, the vector store, or the LLM is unavailable: queue and use cached
  embeddings, fall back to keyword-only, serve cached or templated answers. When
  eval metrics regress, roll back to the last known-good index snapshot while
  you investigate rather than debugging in production.

## When to apply / trade-offs
This applies to any product that answers questions over customer-supplied or
customer-scoped documents, and it becomes non-negotiable the moment more than
one tenant's content shares an index or a cache. The costs are real: hybrid
retrieval roughly triples the setup complexity of a single vector index and
pushes typical latency from the 50-200 ms band into the 80-300 ms band before
any reranking, and the eval harness plus per-tenant observability is a
standing engineering commitment rather than a one-off. Skip most of it for a
single-tenant FAQ bot over a few hundred documents with conversational queries
and no identifier lookups — there, plain vector search with a strict latency
budget is the right answer, and the article says so explicitly. Also note the
economics cut both ways: at small scale a general-purpose relational database
with a vector extension carries the workload (the piece puts the crossover
near 100M embeddings, or earlier if you need multi-region), so reaching for a
dedicated vector service on day one is usually premature. Finally, the source
is a consultancy's architecture guide, so its stack recommendations and dollar
figures are a snapshot of one practice's defaults, not benchmarked results —
treat the numeric thresholds as starting points to be re-measured, which is
precisely what the eval-harness advice tells you to do anyway.

## Fidelity check
1. Claim: tenant filters must be applied before similarity search rather than
   after. Support: the capture states that pipelines filtering later still pull
   other tenants' embeddings into memory and can leak them via prompt
   manipulation, and separately recommends failing closed when tenant context
   is absent.
2. Claim: reciprocal rank fusion uses a constant of about 60 and is preferred
   when score scales diverge. Support: the capture gives the summation of
   1/(k+rank) with k approximately 60 and explains it focuses on rank order,
   making it useful when scales differ drastically or one engine returns zero
   scores.
3. Claim: reranking should be dropped if it does not improve metrics by at
   least roughly 10%. Support: the capture states that if reranking does not
   improve metrics by 10% or more you should skip it because you are trading
   latency and cost for minimal benefit; a separate FAQ entry sets the trigger
   for adding reranking at hybrid precision@5 below 80%.
