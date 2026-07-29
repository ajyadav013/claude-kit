---
source: https://www.ragie.ai/blog/the-architects-guide-to-production-rag-navigating-challenges-and-building-scalable-ai
author: Artem Oppermann (Ragie)
license-note: ideas absorbed in own words; no text or code reproduced
---

# The prototype-to-production gap in RAG is chunking, reranking, and caching

## What it teaches
RAG decomposes into three components — a knowledge base holding indexed
content, a retriever that embeds the query and searches for relevant
fragments, and a generator that merges those fragments with the user
question into one prompt. Frameworks make this assemblable in an
afternoon; what breaks in production is everything around it. The piece
walks the failure surface in order: ingestion (heterogeneous sources,
OCR, nested-iframe scraping, spreadsheet type inference), chunking
(fixed-length splitting orphans tables from their captions), retrieval
(embedding similarity is not query intent — a homonym query can return
the wrong domain entirely), and operations (multi-store query paths add
network hops; high-dimensional vectors thrash memory bandwidth; corpus
storage grows linearly with chunk count). It then gives the countermeasures
— hierarchical or semantic chunking, query decomposition, cross-encoder
reranking, two-level caching, batching, sharded ANN indexes — and closes
on evaluation and on the security posture a scaled index demands.

## Key patterns & decisions
- **Chunking strategy is a retrieval-quality decision, not a preprocessing
  detail** — blind fixed-length splitting (the article's example: every 512
  tokens) severs tables from their labels and code from its comments,
  producing orphan fragments the retriever later misreads. Bad chunks are
  named as a direct cause of downstream hallucination.
- **Hierarchical vs semantic chunking is a corpus-shape choice** —
  hierarchical (document → section → clause, each node pointing at its
  parent) fits structured corpora like contracts, API specs, and manuals,
  and lets the retriever widen or narrow granularity. Semantic chunking
  splits at discourse boundaries so each chunk carries one atomic idea, and
  fits narrative content: blogs, FAQs, transcripts.
- **Both chunking strategies cost you something measurable** — pulling a
  parent node alongside its children can double or triple the token payload
  and threaten the context window; smaller semantic chunks improve precision
  but push you toward a larger top-k, which lengthens retriever search time.
- **Decompose multi-clause queries before embedding** — a compound question
  compressed into one vector retrieves poorly. Split it (via heuristics or
  an LLM parse) into focused subqueries, embed and search each separately,
  then have an orchestrator merge the returned passages.
- **Rerank with a cross-encoder after top-k, not instead of it** — vector
  search is fast but intent-blind; a cross-encoder scores each retrieved
  chunk jointly with the query and reorders on true relevance. The article's
  illustration is a health-benefits-of-apples query pulling in corporate
  Apple documents that a reranker demotes.
- **Cache at two distinct levels** — a retriever-level cache reuses prior
  vector-search results for identical or near-identical queries, avoiding
  index IO; a prompt-level cache hashes the question together with its
  retrieved context (SHA256 is the given example) and returns the stored LLM
  response outright. The second is most valuable for FAQ-shaped traffic.
- **Scale out along two independent axes** — shard the embedding index into
  per-node HNSW indexes and merge top-k across shards (search capacity then
  grows roughly linearly with shard count); separately, decouple retriever,
  reranker, and generator as queue-connected services (Kafka or Redis
  Streams named) so a slow stage absorbs spikes instead of blocking.
- **Evaluate retrieval and generation as two different things** — retrieval
  precision and recall for passage selection, ROUGE-L or BERTScore against
  references for generated text, plus Likert-scale human review. The piece
  is explicit that a strong ROUGE score does not guarantee the output is
  actually comprehensible to a reader.
- **A scaled vector index is a new data-protection surface** — encrypt
  embeddings at rest, TLS in transit, attach row-level access tags to each
  block before indexing, isolate per-client prompt queues, and detect and
  redact or hash PII *before* embedding, so a leaked index cannot be
  inverted back into secrets. Audit-log every retrieval and generation call.

## When to apply / trade-offs
Apply this when a working RAG demo is about to carry real traffic over a
real corpus — the article is explicitly about the prototype-to-production
gap, not about getting retrieval working at all. The costs are concrete and
compounding: hierarchical chunking inflates token payloads, reranking adds
a second model to the request path, query decomposition multiplies searches
per question, and the multi-store query path (vector index plus keyword
index plus sometimes a relational or graph store) adds tens of milliseconds
per hop. Storage is not free either — the article's arithmetic puts a
1536-dimension float16 embedding with metadata near 3 KB, so a 500-million-
chunk corpus lands around 1.5 TB. Skip most of this for a small, uniform,
low-traffic corpus where naive chunking plus top-k already answers well;
adding a reranker and a shard topology there buys latency and operational
burden for no measurable recall. Note also that the source is vendor-
published: its framing points toward managed RAG-as-a-service, so treat the
build-vs-buy conclusion as positioned, while the failure taxonomy itself
stands on its own.

## Fidelity check
1. Claim: fixed-length chunking at a 512-token boundary separates tables
   from labels and code from comments, creating orphan fragments. Support:
   the capture states exactly this, naming 512 tokens as the example
   interval and "orphaned fragments" as the result the retriever
   misinterprets.
2. Claim: sharded HNSW indexes make search capacity scale near-linearly with
   shard count. Support: the capture describes splitting the corpus across
   HNSW indexes on separate nodes, fanning the query out, merging top-k
   hits, and states search capacity scales almost linearly with shards.
3. Claim: a 500-million-chunk corpus needs roughly 1.5 TB of primary
   storage. Support: the capture gives ~3 KB for a 1536-dimensional float16
   embedding including metadata and derives ~1.5 TB for 500 million chunks.
