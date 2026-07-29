---
source: https://www.cloudaeon.com/insights/building-production-grade-rag-architecture:-the-engineering-playbook
author: Cloudaeon Technologies Ltd
license-note: ideas absorbed in own words; no text or code reproduced
---

# Access control belongs in candidate generation, not after retrieval

## What it adds beyond the primary
Sharpens three surfaces the primary only gestures at. First, permission
enforcement is placed *inside* the retrieval pipeline — ACL and
attribute filters run between candidate generation and reranking, with
`acl_attributes` carried on the canonical document record from ingestion,
because post-hoc filtering forces a leak-or-drop trade-off. Second, it
names hybrid retrieval (BM25 for exact identifiers, codes and named
entities, merged with vector ANN under de-duplication and source-diversity
constraints) as the production baseline, and adds a minimum relevance
threshold on the reranker as an explicit safety control — refusal is
preferred over fabricated evidence. Third, it splits evaluation into
retrieval metrics (recall@k, MRR, nDCG, evidence hit-rate) versus
generation metrics (groundedness, citation correctness, refusal
behaviour, format adherence), and defines golden sets by expected
*evidence* rather than expected answers, with regression runs triggered by
document updates, embedding refreshes, model changes and prompt edits. It
also argues context packing must be deterministic — ordered by reranker
score and constrained by recency and near-duplicate suppression — since
non-deterministic packing turns small score jitter into large answer
variance, and warns against tracking average latency instead of tail
behaviour.

## Primary source for this cluster
`aie-063-the-architects-guide-to-production-rag.md`

## Fidelity check
1. Claim: applying permissions after retrieval produces a binary failure —
   either content leaks or the best evidence is dropped. Support: the
   capture states this directly under the access-control-leakage failure
   mode and lists post-retrieval permission filtering among the
   anti-patterns.
