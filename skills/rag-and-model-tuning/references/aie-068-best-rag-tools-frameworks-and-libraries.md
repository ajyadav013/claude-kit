---
source: https://aimultiple.com/retrieval-augmented-generation
author: Ekrem Sarı (AIMultiple)
license-note: ideas absorbed in own words; no text or code reproduced
---

# The vector engine buys latency and governance, not retrieval accuracy

## What it adds beyond the primary

The primary treats RAG as an engineering surface; this piece supplies the
measured numbers that turn each stage into a defensible buying decision.
Three findings are load-bearing. First, component quality does not track
size or price — the top embedding model on a three-domain nDCG@3 test
(voyage-3.5, 0.9429) beat its own vendor's larger flagship at half the
per-token cost, and a 149M-parameter cross-encoder reranker matched a
1.2B one, while adding any reranker lifted top-1 hit rate from 62.67% to
83.00%. Second, held at a matched Recall@10 of 0.95 on identical
embeddings, seven open-source engines landed inside a 0.014 nDCG@10 band
against a 10x single-thread throughput spread (Redis 764 QPS, LanceDB
70) and a 3.7x peak-memory spread at 2.25M vectors (Milvus 17.0 GB,
Chroma 62.4 GB) — the engine is an ops choice, not an accuracy one.
Third, and most useful for anyone writing eval rules, retrieval metrics
split into two halves that can move in opposite directions: scaling a
corpus from 50k to 2.25M vectors dropped nDCG@10 from roughly 0.81 to
0.56 while every engine still reported Recall@10 above 0.973, so an
index-only benchmark would have certified a corpus that had lost about a
third of its answer quality. The piece also puts a cost floor under the
RAG-versus-long-context argument (retrieval wins above roughly 500K
corpus tokens and a few thousand queries a day; below ~200K tokens and a
few hundred queries a day, long context with prompt caching wins outright
because the vector database's fixed hosting bill exceeds the entire
long-context bill), and it insists permission-aware retrieval, identity-
provider sync, per-retrieval audit logging, and data residency are
enforced in the retrieval layer rather than the app above it — noting
that of the seven engines only pgvector offers point-in-time recovery
plus row-level security, that Chroma 1.x ships no authentication, and
that none encrypts at rest natively.

## Primary source for this cluster

[aie-063-the-architects-guide-to-production-rag.md](aie-063-the-architects-guide-to-production-rag.md)

## Fidelity check

1. Claim: seven open-source engines span 0.014 nDCG@10 at matched
   Recall@10 0.95 on identical embeddings. Support: the capture states
   the seven were benchmarked on identical bge-m3 embeddings, each read
   at a matched Recall@10 of 0.95, with nDCG@10 between 0.803 and 0.817,
   a spread of 0.014.
