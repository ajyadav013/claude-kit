---
name: rag-and-model-tuning
description: Choose between retrieving knowledge at inference time and training it into weights, then build either well — chunking, hybrid search, rank fusion, reranking, retrieval evals, LoRA, distillation. Use when a model lacks knowledge your product needs.
---

# RAG and Model Tuning

Your model does not know something it needs to know. There are exactly two families of answer: hand it the knowledge at inference time (retrieval), or write the knowledge into the weights (fine-tuning, distillation). They differ on freshness, attribution, per-user access control, and the shape of the bill — and the wrong choice is usually invisible until production. This skill covers the decision first, then how to build a retrieval pipeline that survives real traffic and how to tune a model when retrieval genuinely cannot reach the bar.

## When to use

- Deciding whether a knowledge gap should be closed by retrieval, by fine-tuning, or by neither
- Designing a RAG pipeline from scratch — ingestion, chunking, indexing, retrieval, reranking, generation
- Debugging a RAG system that answers confidently but wrongly, where the right passage never reached the prompt
- Choosing or tuning a chunking strategy, or recovering from fixed-size chunking that severed tables, code, or clauses
- Adding lexical/BM25 retrieval alongside vector search, and choosing a fusion strategy
- Deciding whether a reranker earns its latency and per-query cost
- Building an evaluation harness for a retrieval system, or attributing a quality regression to retrieval versus generation
- Scoping a multi-tenant retrieval index so one customer's documents can never surface in another's answer
- Planning a fine-tune, a LoRA adapter, or a distillation run to cut inference cost on a narrow high-volume task
- Reviewing an existing RAG or fine-tuning proposal before it becomes a standing operational commitment

Scope boundary — this skill owns **knowledge injection**: getting facts the model lacks into an answer, and measuring whether that worked. Adjacent territory is owned elsewhere:

- Prompt-injection defense for untrusted content (spotlighting, pattern screens, layered defense) belongs to `.claude/rules/agent-guardrails.md` (always loaded). The retrieval-specific section below points there rather than restating it.
- General eval discipline (eval-set-first, grader choice, LLM-as-judge calibration, regression gating) belongs to `.claude/rules/evals.md`. This skill adds the RAG-specific decomposition on top of it.
- Prompt construction, context-window budgeting, and what goes in the system prompt belong to the `context-engineering` skill.
- Trace plumbing for LLM calls — spans, token accounting, cost dashboards — belongs to `langfuse-llm-tracing`.

## Core conventions

### Walk the adaptation ladder top-down and stop early

1. **The ladder is ordered by cost, and most teams should stop before the bottom rung.** Plain prompting, then few-shot examples, then prompting plus retrieval, then structured reasoning (chain-of-thought, self-consistency), then prompt/prefix tuning, then fine-tuning. Walk it downward and stop as soon as quality is acceptable. Each rung costs more sustained engineering than the one above it, and the bottom two convert a prompt change into a training run.

2. **Fine-tuning does not do three things people expect it to.** It does not fix a knowledge cutoff — it only moves the cutoff to your training snapshot. It does not make a model cite sources. And it gives you no per-user access control, because every caller of a tuned model can reach every fact baked into it. Any product needing freshness, attribution, or row-level permissions keeps retrieval in the design even after it tunes.

3. **Retrieval and tuning are teaching different things.** Retrieval teaches *facts* — what is true right now in your corpus. Tuning teaches *behavior* — output shape, format adherence, tone, tool-call discipline, following a house convention. A knowledge gap is a retrieval problem; a "the model keeps answering in the wrong format" problem is a tuning problem (or, more cheaply, a prompt problem). Misdiagnosing which one you have is the single most expensive mistake in this space.

    | Property | Retrieval | Fine-tuning / distillation |
    |----------|-----------|----------------------------|
    | Teaches | Facts, current state of a corpus | Behavior, format, style, task procedure |
    | Freshness | Re-index and the answer changes | Stale until the next training run |
    | Attribution | Can cite the retrieved passage | Cannot cite; the fact has no provenance |
    | Per-user access control | Enforceable per query, per tenant | None — every caller reaches every baked-in fact |
    | Cost shape | Recurring per request (search, longer prompts) | One-time training, then cheaper per request |
    | Failure mode | Wrong passage retrieved; answer is confidently off | Silent drift as inputs move away from the training distribution |
    | Iteration loop | Minutes — re-chunk, re-embed, re-run evals | Hours to days — a training run per corpus version |
    | Blocking prerequisite | An index and an embedding/search service to operate | Labelled or curated data, plus GPU budget and a rollout plan |

4. **For long-tail facts, retrieval wins decisively — and wins hardest where the fact is rarest.** A controlled comparison across twelve models (80M to 11.3B) and three long-tail QA sets found retrieval moved accuracy far more than fine-tuning on the same synthetic data. Broken out by entity popularity, retrieval's margin was largest in the least-popular bucket: for common entities the model already knew the answer, so retrieval added little. That is the exact shape of most internal-knowledge products — the value is concentrated in the facts pre-training never saw.

5. **Fine-tuning on top of retrieval is not a free additive win.** In that same comparison, combining tuning with retrieval helped models up to roughly 3B parameters and *degraded* models in the 7B–11.3B range, apparently by eroding the in-context reasoning the retrieval prompt depends on. If you tune a model that will later be served with retrieved context, prefer parameter-efficient tuning over full tuning — full tuning scored better without retrieval and collapsed with it.

6. **Try re-ordering the evidence before you train anything.** The cheapest recovery of what fine-tuning appeared to buy was ordering: split the top retrieved documents into sentences, re-rank the sentences against the query, and prepend the single most relevant one at the very top of the prompt as an explicit hint. No new information enters the prompt — only its salience changes — and it beat the fine-tuned-plus-retrieval configuration in every reported case. Exhaust ordering and reranking before opening a training budget.

7. **The default sequencing.** Build retrieval. Invest in retriever quality and in reranking down to the most relevant span. Cap the packed context at a small number of documents. Only then consider tuning, only if retrieval demonstrably cannot reach the required accuracy, and only with parameter-efficient methods.

8. **Know where these findings stop.** The evidence above is scoped to short factual questions over encyclopedic corpora with substring-match scoring and models no larger than about 11B. Do not extrapolate it to multi-hop reasoning, long-form generation, style adaptation, or frontier-scale models. For teaching behavior and output shape, tuning remains the right tool.

9. **Walk the whole path before designing any one stage.** Every box below maps to a section of this skill, and a design review that cannot walk the path has found its gap.

    ```
    ingest:  source → parse → chunk (structural) → attach metadata + ACL
             → embed → vector index
             → tokenize → lexical index          (same ACL scoping, mirrored)

    query:   question → decompose into subqueries → apply tenant/ACL filter
             → vector search (top 20-30) ┐
             → lexical search (top 20-30) ┴→ fuse (RRF or weighted)
             → rerank (cross-encoder) → drop below relevance threshold
             → pack deterministically, best evidence first, ~3 docs
             → generate → cite → guardrail the output

    grade:   retrieval axis (context relevance / precision / recall, nDCG)
             generation axis (faithfulness, answer relevance, citations)
             cost axis (tokens, cost per query, p95 latency)
    ```

### Ingestion sets the ceiling on everything downstream

1. **Most of the unglamorous work lives here, and it is the work that decides quality.** Sources arrive heterogeneous — scanned documents needing OCR, pages whose real content sits inside nested frames, spreadsheets whose column types must be inferred, exports with inconsistent encodings. Every extraction defect becomes a chunk defect, becomes a retrieval defect, becomes a wrong answer. No amount of embedding-model upgrading recovers text that was never extracted correctly.

2. **Give ingestion a canonical document record.** One record per source document carrying a stable ID, the source URI, timestamps, and access-control attributes, with every chunk pointing back at it. That record is what makes eviction, re-indexing, citation, and permission enforcement possible later; without it, each of those becomes a corpus-wide scan.

3. **Make ingestion idempotent and re-runnable.** Re-processing the same source must produce the same chunk IDs, so a partial failure is simply re-run and an updated document cleanly replaces its predecessor instead of accumulating near-duplicates that later crowd out the top-k.

4. **Know who can write into the corpus.** Ingestion is a trust boundary — see the untrusted-content section below. A source anyone can add documents to is a source anyone can inject through, and unlike a one-off fetch the effect persists in the index.

### Chunking is a retrieval-quality decision, not a preprocessing detail

1. **Fixed-size splitting destroys meaning at the boundary.** Cutting every N tokens (512 is the usual default) severs a table from its caption, a code block from the comment that explains it, a clause from the definition it depends on. What lands in the index is an orphan fragment that reads plausibly and means something different from the passage it came from. Bad chunks are a direct upstream cause of confident hallucination — the model reasons correctly over context that was already wrong.

2. **Split on structure, not on arithmetic.** Use headings, list items, table boundaries, and paragraph breaks as split points, with a token budget as a constraint rather than the rule. A useful starting band is roughly 300–600 tokens per chunk, then measured against your own eval set.

3. **Choose the strategy from the corpus shape.** Hierarchical chunking (document → section → clause, each node pointing at its parent) fits structured corpora — contracts, API specifications, manuals, policy documents — and lets retrieval widen or narrow granularity by walking the tree. Semantic chunking splits at discourse boundaries so each chunk carries one atomic idea, and fits narrative content — articles, FAQs, transcripts, support threads.

4. **Both strategies cost something measurable.** Pulling a parent node alongside its children can double or triple the token payload and threaten the context window. Smaller semantic chunks improve precision but push you toward a larger top-k, which lengthens search time and re-imports noise. Neither is free; pick against measurements, not aesthetics.

5. **Carry metadata on every chunk from ingestion.** Source document ID and URI, section path, creation and last-modified timestamps, and the access-control attributes the retrieval layer will filter on. Metadata that is not attached at ingestion cannot be filtered on at query time without a second lookup.

6. **Treat the chunking configuration as a versioned artifact.** A change to split rules, chunk size, or overlap is a version bump: it invalidates every cached embedding and retrieval result, and it forces a re-run of the eval suite before release. Keep ingestion idempotent so a re-run over the same source produces the same chunk IDs, and retain both the raw and the processed form so a bad transform is auditable and reversible.

### Hybrid retrieval is the baseline, not an optimization

1. **Pure vector search has three named blind spots.** *Exact identifiers* — a ticket number or SKU retrieves semantically adjacent identifiers rather than the one asked for. *Precise jargon* — domain acronyms and near-synonyms get blurred together in embedding space. *Recency* — an embedding carries no notion of time, so "the latest policy" is unanswerable from similarity alone. Lexical search covers the first two; metadata date filters cover the third.

2. **Run both engines in parallel and cap each candidate list.** Roughly the top 20–30 hits per engine is a workable starting point. The point of the cap is that fusion and reranking downstream are the precision stages; the retrieval stage exists to make sure the right chunk is *somewhere* in the candidate pool.

3. **Fusion is an algorithm you choose, not a thing that happens.** Three options, by situation:
    - **Weighted score combination** when both engines return comparable, calibrated score scales.
    - **Reciprocal rank fusion** when the scales diverge or one engine returns no usable score — sum `1/(k + rank)` across engines with `k` around 60. It discards magnitudes entirely and merges on rank order, which is exactly why it is robust to incomparable scoring.
    - **A learned fusion model** when you have labelled click or judgement data and a retraining pipeline to keep it current.

4. **Weight the blend to the corpus, then prove it offline.** Narrative documentation skews heavily to the vector side; mixed corpora carrying identifiers land near an even split; regulated, legal, or code-like text inverts toward keyword dominance. Whatever ratio you pick, validate it against a historical query set before you A/B it on live traffic — the offline set is cheap and the live experiment is not.

5. **The retriever is the system's accuracy ceiling.** In the long-tail comparison, recall@1 across four retrievers spanned roughly 40 to 59 points and downstream answer accuracy tracked it directly. Upgrading the retriever or the embedding model is almost always a cheaper accuracy lever than touching the generator, and the best embedding model on a benchmark is frequently not the largest or most expensive one from that vendor.

6. **Filter before you search, and fail closed.** In any multi-tenant or permissioned product, the tenant/ACL predicate goes *inside* the query to both engines, not applied to the result set afterward. A post-filter has already pulled another customer's embeddings into the process, where prompt manipulation or a logging bug can surface them; it also forces a leak-or-drop trade-off when the best evidence is out of scope. If tenant context is missing from the request, abort the response — never default to unscoped retrieval.

7. **The lexical index is the forgotten leak path.** Teams reliably scope the vector store and forget the keyword index, which then serves the same cross-tenant content by another door. Whatever isolation mechanism the vector side uses — namespaces, row-level security, query filters — mirror it verbatim on the lexical side, and re-validate every retrieved chunk against the requesting tenant before it enters the prompt.

### Rerank as a second-stage precision filter, with a stop rule

1. **Reranking scores query and document jointly; retrieval does not.** Vector and lexical search are fast because they compare pre-computed representations. A cross-encoder reranker reads the query and each candidate together and produces a true relevance score, which is why it catches the failure where a query about the health benefits of apples returns corporate filings about a company named Apple. It runs *after* top-k, never instead of it.

2. **Have an explicit trigger and an explicit removal rule.** Add a reranker when precision@5 is still below roughly 80% after hybrid retrieval has been tuned, or when queries are genuinely multi-clause. Remove it when the measured lift falls under roughly 10% — below that you are paying latency and per-query cost for noise. Both numbers are starting points to re-measure on your own eval set, not constants.

3. **The reranker options differ by an order of magnitude in latency and cost.** These are categories, not product recommendations, and the figures are reported starting points to re-measure on your own traffic:

    | Category | Typical latency | Typical cost per query | What it demands of you |
    |----------|-----------------|------------------------|------------------------|
    | Managed cross-encoder API | ~100–300 ms | fractions of a cent | A vendor dependency on the request path |
    | Self-hosted cross-encoder | ~50–150 ms | infrastructure only | GPU capacity and model ops |
    | LLM as reranker | ~300–800 ms | one to two orders more | Nothing new to run, but the largest bill and tail |
    | Learned fusion over click data | under ~50 ms | negligible | Labelled interactions and a retraining pipeline |

    An end-to-end latency budget under about 200 ms rules out most of these — decide the budget before choosing the stage.

4. **Reranker size does not track reranker quality.** Small cross-encoders have been measured matching models an order of magnitude larger on the same task, while *adding any* reranker moved top-1 hit rate by around twenty points. Choose on measured lift per millisecond, not on parameter count.

5. **Set a minimum relevance threshold and let the system refuse.** If nothing clears the bar after reranking, returning "I don't have that" is a correct answer. Passing weak evidence into the prompt because the pipeline must always produce something is how a retrieval bug becomes a fabrication.

6. **Pack the context deterministically.** Order by reranker score, suppress near-duplicates, apply recency constraints explicitly. Non-deterministic packing turns small score jitter into large answer variance, which makes both debugging and regression testing unreliable.

7. **More retrieved documents is not monotonically better.** Going from one document to three typically gives a clear gain; going to five often gives nothing or a regression, even when recall@5 exceeds recall@3. Extra context is noise the model must filter, and it competes for attention with the passage that actually answers the question.

8. **Position is a free lever.** Evidence placed at the start of the prompt gets disproportionate attention. Rerank down to the single most relevant sentence or span and put it first, with the fuller passages behind it.

### Query handling before the index is touched

1. **Decompose multi-clause questions before embedding.** A compound question compressed into one vector retrieves poorly for all of its parts. Split it — heuristically or with a cheap model call — into focused subqueries, search each independently, then merge the returned passages. The cost is that each question now fans out into several searches; budget for it.

2. **Route recency and identifier questions to the mechanism that can answer them.** A date filter on metadata answers "what changed last quarter"; a lexical exact match answers "what does ticket ABC-1234 say". Neither is a similarity problem, and neither improves by tuning the embedding model.

3. **Cache at two distinct levels.** A retriever-level cache reuses search results for identical or near-identical queries and avoids index I/O. A prompt-level cache keys on a hash of the question *together with* its retrieved context and returns the stored response outright — most valuable for FAQ-shaped traffic. Both are invalidated by a chunking change, an embedding refresh, or a prompt edit; wire that invalidation in when you add the cache, not after the first stale-answer incident.

### Evaluate retrieval and generation as separate subsystems

1. **A single quality score tells you the system broke, not which part.** The organising decomposition is the RAG triad — **context relevance** (did retrieval find the right material), **faithfulness/groundedness** (is every asserted claim supported by what was retrieved), and **answer relevance** (does the response address the question that was asked). Because the three axes move independently, a drop points at a specific subsystem.

2. **Add two rank-aware retrieval refinements.** **Context precision** weights early chunks more heavily, because chunks near the top of the packed context disproportionately steer generation. **Context recall** asks whether everything needed to answer was retrieved at all. Alongside them, the classical retrieval metrics still apply — recall@k, MRR, nDCG, evidence hit-rate.

3. **Map each metric to the subsystem it blames, so a regression has an owner.** This mapping is the whole reason for splitting the score:

    | Metric | Axis | What a drop means | Where to look first |
    |--------|------|-------------------|---------------------|
    | Context recall / recall@k | Retrieval | The answer was never in the candidate pool | Chunking, embedding model, hybrid coverage, ACL over-filtering |
    | Context precision / nDCG / MRR | Retrieval | The right chunk was found but buried | Fusion weights, reranking, top-k size |
    | Faithfulness / groundedness | Generation | The model asserted what the context did not support | Prompt, packing order, context length, model choice |
    | Answer relevance | Generation | Grounded but off-question | Query decomposition, prompt instructions |
    | Citation accuracy | Generation | Cited a source that does not support the claim | Citation prompt, chunk-to-source mapping |
    | Refusal behavior | Both | Answering when it should decline, or the reverse | Minimum relevance threshold, refusal instructions |

4. **Retrieval metrics can move in opposite directions, and the misleading one is the flattering one.** One published benchmark grew a corpus roughly 45x, into the millions of vectors, and watched nDCG@10 fall by about a third — while recall stayed near-perfect on every engine tested. Recall reported that nothing had changed; ranking quality had in fact collapsed. Judged on recall alone that corpus would have passed. Always report a rank-sensitive metric beside recall.

5. **Compute faithfulness by claim decomposition.** Split the generated answer into atomic factual claims, check each against the retrieved passages, and report the supported fraction. This is what stops fluent prose from inflating the score. Compute answer relevance in reverse — have a model generate the questions the answer would plausibly be answering, then compare those to the real query.

6. **Do not use n-gram overlap metrics here.** BLEU and ROUGE compare an output against a gold string; they can detect neither hallucination nor whether the retrieved context was used at all. A strong overlap score is compatible with a completely ungrounded answer.

7. **Define golden sets by expected evidence, not expected answers.** "This query must retrieve document X, section Y" is a stable assertion that survives prompt edits and model swaps; "the answer must be this paragraph" is not. Layer generation-side assertions on top — groundedness, citation correctness, refusal behavior on out-of-scope queries, format adherence.

8. **Size and stratify the eval set deliberately.** Start around 100–200 representative queries and add batches of roughly 25 until metrics stabilise across consecutive runs. Stratify across factual lookup, multi-hop, policy questions, ambiguous phrasing, and known edge cases, so a regression in one query class cannot hide inside an aggregate. The general discipline for building and grading these sets lives in `.claude/rules/evals.md`.

9. **Name the triggers that force a regression run.** Document/corpus updates, embedding model refreshes, generator model changes, prompt edits, and chunking changes. Each one can shift retrieval without any code diff to review.

10. **Grade cost and latency in the same pipeline as quality.** Tokens, cost per query, and p50/p95 latency belong on the same run as faithfulness. Track tail latency, not the average — an average hides exactly the queries where the reranker or the fan-out blew the budget. Gate the release on both axes: block if faithfulness degrades or p95 exceeds target on the regression set.

11. **Watch for the regression this all exists to catch.** Prompt rewrites, chunking changes, and retriever swaps routinely make answers *read* better while grounding and citation accuracy quietly fall. That failure is invisible to human spot-checking and obvious to a claim-decomposition metric.

12. **Keep evaluating in production.** Sample a fraction of live traffic, always evaluate high-stakes query classes, and run the grading asynchronously off the request path. Tooling here splits into open metric libraries, trace-visibility tools, assertion-style libraries that run inside CI, and managed platforms — choose by whether you need control or hosted dashboards, and see `langfuse-llm-tracing` for the trace plumbing underneath.

### Retrieved passages are untrusted content

1. **The general defense is already written down.** Retrieved text is external content and must be treated as data, never as instructions — spotlighting/delimiter-marking, pattern screening, and the layered-defense stance are owned by `.claude/rules/agent-guardrails.md` (always loaded). Apply it; do not re-derive it here.

2. **What is specific to retrieval is that the index makes injection persistent.** A poisoned page fetched once affects one request. A poisoned document that gets ingested, chunked, and embedded affects every future query that retrieves it, for as long as it sits in the index. Treat ingestion as a trust boundary with its own review: know which sources can write into the corpus, and be able to identify and evict a document from the index and every downstream cache.

3. **Enforce permissions during candidate generation, not after.** Carry access-control attributes on the canonical document record from ingestion and apply them between candidate generation and reranking. Post-hoc filtering forces the leak-or-drop trade-off described above.

4. **Detect and redact or hash PII before embedding, not after retrieval.** Once a secret is inside a vector it is inside every backup, replica, and cache of that index, and embeddings are not a one-way function in any security-relevant sense. Encrypt embeddings at rest, use TLS in transit, and be aware that many vector engines ship without native at-rest encryption or even authentication — verify rather than assume.

5. **Audit-log every retrieval.** Sanitized query, tenant, retrieval mode, chunk IDs and scores returned, rerank decision, guardrail verdict, and per-query cost. Dashboard precision and recall per tenant, latency percentiles, per-tenant token burn, and cross-tenant access attempts — the last should be a flat zero line that alerts on any deviation. Broader application-security context lives in `security-and-hardening`.

### When tuning is the right answer, pick the cheapest kind that works

1. **Parameter-efficient tuning is the default; full fine-tuning is the exception.** Full tuning updates every layer, costs the most, and risks catastrophic forgetting of general capability. PEFT freezes most of the network and trains a small subset — it does better in low-data regimes, generalises better out-of-domain, and produces a compact, portable checkpoint.

2. **LoRA is the workhorse.** It injects trainable low-rank matrices (classically at the attention query and value projections) on the premise that the useful weight update is intrinsically low-rank; a 1000×1000 update factored through rank 8 drops a million trainable parameters to sixteen thousand. Two knobs matter — rank `r` and scaling `alpha`, with the effective contribution scaled by `alpha/r`. Too small under-adapts, too large destabilises training; `alpha` at roughly twice the rank is a commonly reported operating point.

3. **Adapters buy swappability; merging buys latency.** One base model plus one small adapter per task means a hundred downstream tasks cost a hundred adapters, not a hundred model copies. When serving latency matters more than swappability, merge the LoRA weights back into the base so inference pays no extra hop.

4. **Quantized tuning trades wall-clock for memory.** Loading the base in 4-bit while keeping the adapters in higher precision brings large models onto single-GPU budgets — reported cases include a 40B model halving its VRAM requirement and a 65B fine-tune collapsing from a multi-GPU job to a single-accelerator one — at a cost of roughly half again the training time. Take the trade when memory is the binding constraint, not by default.

5. **If the tuned model will be served with retrieval, train it for that.** Retrieval-aware tuning explicitly trains the model to use relevant retrieved passages and ignore distractor documents, which is a different objective from teaching it facts.

6. **Watch the imitation-data failure mode.** Piling on data that imitates a stronger model teaches the student the teacher's *style* rather than its *content*, and can degrade the student outright. Quality of training data dominates quantity — in one comparison, a generator that produced twelve times fewer examples via a careful chain-of-thought template trained consistently better models than a high-volume end-to-end generator.

### Distillation — buy frontier behavior at a small model's price

1. **Curated behavior cloning is the highest-leverage variant.** Run the strong model in production, keep only the episodes a success metric marked as passing, and supervised-fine-tune a small model on those transcripts. Reported reductions in *cost per success* ranged from under 2x to over 30x across extraction, navigation, agentic retrieval, and tool-using tasks, with latency dropping 2–4x, training sets of only a few hundred successful conversations, and one-time training bills in the tens of dollars.

2. **The curation filter does most of the work, so the real prerequisite is observability.** You need a programmatic success signal you are already logging, and complete request/response episodes with an outcome label. Ablations comparing curated against uncurated training sets favour curation consistently. If you cannot compute success without expensive human review, this technique is not available to you yet — fix the logging first.

3. **Score on cost per success, never cost per token.** A cheap model that fails half the time is not cheap. Divide cost per task by success rate and the comparison becomes honest.

4. **Measure reliability separately from success.** Report both single-shot success and all-of-k repeat success. A distilled model can hold its single-shot rate while quietly losing consistency, and only the repeat view exposes that.

5. **Distil per policy in a multi-agent loop.** Where a pipeline has distinct roles — generate the next search query, extract notes from results — fine-tune a separate small model per role using successful whole-episode demonstrations. No per-role reward signal is needed.

6. **Self-distillation is the better shape for injecting knowledge into weights.** Run the *same* model twice — once with the source document in its prompt, once without — and minimise the divergence between their output distributions. Because teacher and student share a network, there is no style mismatch to launder and the gradient is spent on facts rather than on imitating another model's voice. Reported results beat plain supervised tuning at roughly an order of magnitude less data, and stacking it with retrieval beat retrieval alone. Add a second divergence penalty against unrelated instruction data to hold general capability steady. Note the prerequisites — open weights and logit access, so this is unavailable behind a closed inference API, and re-distilling is slower than re-indexing when facts change.

7. **You can also distil into text instead of into weights.** Give the model an entire demonstration set and ask it to write out the core knowledge the task needs; keep the resulting summary and send only that, plus a couple of format examples, at inference time. One study matched many-shot accuracy at roughly a twentieth of the input tokens and landed level with demonstration retrieval while removing the retrieval index entirely. Two properties make this attractive beyond the token saving — it works on closed models that cannot be fine-tuned, and the artifact is human-readable and directly editable, so a diagnosed failure can be fixed by editing a paragraph. It only pays where many-shot genuinely beats few-shot for that task, so check that on a small subset first.

8. **Prefer a one-time training cost to a recurring inference-time one.** Best-of-n sampling, long chain-of-thought, and dynamic in-context example selection all multiply the cost of *every* request. Distillation front-loads the spend once and amortises over volume — which is precisely why it fits narrow, high-volume, repeatedly-executed tasks and not open-ended low-volume work.

9. **Deploy behind a router and keep the escape hatch.** Send the bulk of traffic to the distilled model, escalate hard cases to the strong model, and ramp the split gradually while watching quality metrics. Expect a performance floor on genuinely hard agentic tasks — recovering ~90% of the teacher's accuracy at a fraction of the cost is a routing decision, not a failure, provided you decided in advance what accuracy delta you can absorb.

10. **Budget for permanent drift surveillance.** A distilled student learned one input distribution and degrades silently as inputs evolve. Do not treat out-of-distribution reuse as free either — students fine-tuned on one domain and run on an adjacent one have been measured regressing below their own zero-shot baseline, while the latency gains transferred intact.

### Operate the pipeline

1. **Design the degraded modes up front.** Name the behavior when the embedding service is unavailable (queue the work, serve cached embeddings), when the vector store is unavailable (fall back to keyword-only), and when the generator is unavailable (cached or templated answers). Undesigned degradation defaults to a 500 on the whole feature.

2. **Keep index snapshots and roll back to them.** When eval metrics regress after an ingestion or embedding refresh, restore the last known-good index snapshot and investigate offline rather than debugging in production.

3. **Scale along two independent axes.** Shard the vector index across nodes and merge top-k across shards; separately, decouple retriever, reranker, and generator into queue-connected stages so a slow stage absorbs spikes instead of blocking the request path.

4. **The vector engine is an ops choice, not an accuracy choice.** Held at matched recall on identical embeddings, a spread of open-source engines has been measured landing inside a hair's breadth on ranking quality while differing by roughly 10x in single-thread throughput and several-fold in peak memory. Choose on throughput, memory, operational maturity, and — importantly — on which one supports the permission model, point-in-time recovery, and residency guarantees you need. A general-purpose relational database with a vector extension carries a surprising amount of load; reaching for a dedicated vector service on day one is usually premature.

5. **Size the storage before you commit.** A 1536-dimension half-precision embedding with metadata lands near 3 KB, so a corpus of 500 million chunks is on the order of 1.5 TB of primary storage before replicas. Corpus storage grows linearly with chunk count, which is a second reason chunk size is an architectural decision.

6. **Below a threshold, long context plus prompt caching beats retrieval outright.** For a small corpus and modest query volume, a vector database's fixed hosting bill can exceed the entire long-context bill. Retrieval starts winning as corpus size and query volume grow. Do the arithmetic for your own numbers before standing up an index; see `performance-optimization` for the general cost/latency framing.

## Anti-patterns to avoid

1. **Fine-tuning to fix a knowledge gap** — it moves the cutoff rather than removing it, cannot cite sources, and grants every caller access to every baked-in fact. Retrieval is the mechanism for facts; tuning is the mechanism for behavior.
2. **Bolting a fine-tune onto a working RAG pipeline and assuming it adds** — measured results show it helping small models and degrading mid-size ones by eroding in-context reasoning. Measure the combination, never assume it.
3. **Full fine-tuning a model that will be served with retrieved context** — the configuration most likely to destroy the in-context reasoning the retrieval prompt depends on. Use parameter-efficient methods.
4. **Fixed-size chunking as the default** — severs tables from captions and clauses from definitions, producing orphan fragments that read plausibly and mean something else. Split on structure.
5. **Treating chunk configuration as a constant** — a change to split rules silently invalidates every embedding, every cache, and every eval baseline. Version it and re-run the suite.
6. **Vector-only retrieval in a corpus containing identifiers, acronyms, or time-sensitive facts** — three known blind spots that no amount of embedding-model upgrading closes. Add lexical search and metadata filters.
7. **Merging two engines' results by comparing their raw scores** — different engines score on incomparable scales. Use reciprocal rank fusion when the scales diverge, weighted combination only when they genuinely don't.
8. **Adding a reranker without a measured trigger, or keeping one without measured lift** — either way you are buying latency and per-query cost on faith. Add below a precision threshold; remove below a lift threshold.
9. **Post-filtering by tenant or ACL after retrieval** — the other tenant's embeddings are already in the process, and you are left choosing between leaking and dropping the best evidence. Filter inside the query, and fail closed when tenant context is absent.
10. **Scoping the vector store and forgetting the lexical index** — the same cross-tenant content served by a second door. Mirror the isolation on every retrieval path.
11. **Embedding text before PII detection** — once inside the vectors, it is inside every backup and replica of the index. Redact or hash first.
12. **Padding the prompt with more retrieved documents to be safe** — beyond roughly three, extra context is usually noise that competes for attention with the passage that answers the question.
13. **Reporting recall as the retrieval metric** — recall can hold above 0.97 while ranking quality collapses by a third. Always pair it with a rank-sensitive metric.
14. **Grading a RAG system with BLEU or ROUGE** — n-gram overlap against a gold answer detects neither hallucination nor whether the retrieved context was used. Decompose into claims instead.
15. **A single end-to-end quality score** — tells you something broke without telling you which subsystem. Split into context relevance, faithfulness, and answer relevance.
16. **Distilling without a programmatic success signal** — the curation filter is where the gains come from; training on all logged traffic clones the failures alongside the successes.
17. **Comparing models on cost per token** — a cheap model that fails half the time is not cheap. Cost per success is the honest denominator.
18. **Shipping a distilled model with no escalation path and no drift monitoring** — the student learned one input distribution and degrades silently as inputs move.
19. **Tracking average latency for a retrieval pipeline** — fan-out, reranking, and cold shards live entirely in the tail. Gate on p95.
20. **Treating retrieved passages as instructions** — the index is a persistent injection surface, so one poisoned document affects every future query that retrieves it. See `.claude/rules/agent-guardrails.md`.

## References

Digests (own-words summaries of the sources, in `references/`):

- [aie-059-distillation-with-programmatic-data-curation-cheaper-infer.md](references/aie-059-distillation-with-programmatic-data-curation-cheaper-infer.md) — curated behavior cloning, cost-per-success accounting, pass^1 vs pass^k reliability, per-policy distillation, router deployment and drift surveillance
- [aie-060-efficient-knowledge-injection-in-llms-via-self-distillatio.md](references/aie-060-efficient-knowledge-injection-in-llms-via-self-distillatio.md) — self-distillation for knowledge injection, soft vs hard targets, forgetting penalty, distillation stacked with retrieval
- [aie-061-distilling-many-shot-in-context-learning-into-a-cheat-shee.md](references/aie-061-distilling-many-shot-in-context-learning-into-a-cheat-shee.md) — distilling demonstrations into an editable text artifact, accuracy per input token, parity with demonstration retrieval, closed-model applicability
- [aie-062-llm-fine-tuning-customize-large-language-models.md](references/aie-062-llm-fine-tuning-customize-large-language-models.md) — the adaptation ladder, full tuning vs PEFT, LoRA rank/alpha, adapters and merging, quantized tuning, retrieval-aware tuning, what fine-tuning cannot do
- [aie-063-the-architects-guide-to-production-rag.md](references/aie-063-the-architects-guide-to-production-rag.md) — the prototype-to-production failure surface, hierarchical vs semantic chunking, query decomposition, cross-encoder reranking, two-level caching, index sharding, storage arithmetic
- [aie-064-rag-best-practices-chunking-hybrid-search-reranking.md](references/aie-064-rag-best-practices-chunking-hybrid-search-reranking.md) — vector search's three blind spots, fusion strategies and reciprocal rank fusion, reranker add/remove thresholds, filter-before-search and the lexical leak path, retrieval observability, degraded modes
- [aie-065-fine-tuning-vs-retrieval-augmented-generation-for-less-pop.md](references/aie-065-fine-tuning-vs-retrieval-augmented-generation-for-less-pop.md) — the head-to-head comparison on long-tail knowledge, popularity-bucketed gains, model-size interaction, retriever quality as ceiling, document-count saturation, the prepended-hint result
- [aie-067-building-production-grade-rag-architecture-the-engineering.md](references/aie-067-building-production-grade-rag-architecture-the-engineering.md) — permissions inside candidate generation, minimum relevance threshold and refusal, deterministic context packing, evidence-based golden sets, regression triggers
- [aie-068-best-rag-tools-frameworks-and-libraries.md](references/aie-068-best-rag-tools-frameworks-and-libraries.md) — component quality not tracking size or price, engines as an ops choice at matched recall, recall-vs-nDCG divergence at scale, the RAG-versus-long-context cost floor, governance features in the retrieval layer
- [aie-069-rag-evaluation-metrics.md](references/aie-069-rag-evaluation-metrics.md) — the RAG triad, context precision and recall, faithfulness by claim decomposition, reverse-question answer relevance, eval-set sizing and stratification, release gates, continuous production evaluation

Attribution: each digest summarizes the public article or paper named in its own frontmatter — own-words summaries, no verbatim text. Tool and vendor names appearing in the digests are examples of categories, not recommendations.

Related skills and rules:

- `.claude/rules/agent-guardrails.md` (always loaded) — owns prompt-injection defense for untrusted content, including retrieved passages; this skill defers to it rather than restating it
- `.claude/rules/evals.md` (always loaded) — owns general eval discipline (eval-set-first, grader choice, LLM-as-judge calibration, regression gating); the RAG triad here is a decomposition layered on top
- `context-engineering` — prompt construction, context-window budgeting, and what belongs in the system prompt versus the retrieved payload
- `langfuse-llm-tracing` — the trace plumbing for LLM calls that retrieval observability and continuous evaluation sit on top of
- `security-and-hardening` — broader application and LLM-feature security, including the input/output guardrail chain around the model
- `performance-optimization` — general latency and cost framing for the budgets this skill spends on reranking, fan-out, and index hosting
