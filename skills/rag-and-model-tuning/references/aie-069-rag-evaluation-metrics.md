---
source: https://customgpt.ai/rag-evaluation-metrics/
author: Priyansh Khodiyar (CustomGPT.ai)
license-note: ideas absorbed in own words; no text or code reproduced
---

# A single RAG score hides the break; the RAG Triad names which subsystem failed

## What it adds beyond the primary

The primary maps the RAG failure surface (ingestion, chunking, retrieval,
operations); this piece supplies the measurement layer that turns those
failures into numbers. Its organising idea is the **RAG Triad** — Context
Relevance (did retrieval find the right material), Faithfulness /
Groundedness (is each asserted claim supported by what was retrieved),
and Answer Relevance (does the response address the question asked) —
plus two retrieval-side refinements: **Context Precision**, which is
rank-aware because early chunks disproportionately steer generation, and
**Context Recall**, which asks whether everything needed was retrieved at
all. Because the axes are independent, a score drop points at a specific
subsystem rather than at "the RAG system".

Two mechanics are worth carrying over. **Faithfulness is computed by
claim decomposition**: split the answer into atomic factual claims, check
each one against the retrieved passages, and report the supported
fraction — which is why fluent prose cannot inflate the score. **Answer
Relevance is computed in reverse**: have a model generate the questions
the answer would plausibly be answering, then compare those to the real
query by semantic similarity. The article also notes that classical NLP
overlap metrics (BLEU, ROUGE) are structurally unfit here — they compare
n-grams against a gold answer and can detect neither hallucination nor
whether the retrieved context was used.

Operationally it argues for a sized, stratified eval set (start at
100–200 representative queries, add batches of ~25 until metrics
stabilise across consecutive runs, stratify across factual lookup,
multi-hop, policy, ambiguous phrasing, and edge cases), for grading
quality and cost/latency in the *same* pipeline (p50/p95, tokens, cost
per query), and for a concrete release gate — block the release if
faithfulness degrades or p95 exceeds target on the regression set. It
warns about the specific regression that motivates all of this: prompt
rewrites, chunking changes, and retriever swaps can make answers *read*
better while grounding and citation accuracy quietly fall. For a
citation-bearing system it adds **citation accuracy** — verify that each
cited source actually supports the claim it is attached to. Continuous
production evaluation is framed as sampling (a fraction of traffic) plus
an always-evaluate rule for high-stakes queries, run asynchronously off
the request path. Tool choice is positioned by need rather than ranked:
RAGAS as an open-source metric library, TruLens for trace-level
visibility, DeepEval for assertion-style checks inside Python CI, and
managed platforms such as LangSmith or Arize Phoenix when hosted
dashboards matter more than control.

Against `rules/evals.md` this is largely additive rather than
contradictory: the kit already teaches eval-set-first, LLM-as-judge with
calibration, and a regression suite that gates. What is genuinely new is
the *decomposition* — RAG has named, separable failure axes, and the kit
currently has no vocabulary for retrieval-vs-generation attribution.

## Primary source for this cluster

[aie-063-the-architects-guide-to-production-rag.md](aie-063-the-architects-guide-to-production-rag.md)

## Fidelity check

1. Claim: the RAG Triad is Context Relevance, Faithfulness/Groundedness,
   and Answer Relevance. Support: the capture states that these three
   dimensions form the core evaluation framework and names them the RAG
   Triad.
