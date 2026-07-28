---
source: https://arxiv.org/html/2403.01432v3
author: Heydar Soudani, Evangelos Kanoulas, Faegheh Hasibi (Radboud University / University of Amsterdam), SIGIR-AP 2024
license-note: ideas absorbed in own words; no text or code reproduced
---

# Retrieval beats fine-tuning for long-tail facts; one hint sentence beats both

## What it teaches
When a model has to answer questions about entities it barely saw in
pre-training — proprietary terminology, internal knowledge graphs, niche
domain facts — teams reach for one of two knowledge-injection routes:
parametric (fine-tune on synthetic QA generated from your documents) or
non-parametric (retrieve documents into the prompt). This study runs both
routes across twelve models from 80M to 11.3B parameters, three long-tail
QA datasets, four retrievers, two synthetic-data generators and two
fine-tuning regimes. Retrieval wins decisively, and it wins hardest exactly
where the knowledge is rarest. Fine-tuning does help, but it helps small
models and actively degrades the larger ones once retrieval is in play,
apparently by eroding the in-context reasoning the RAG prompt depends on.
The paper then shows that most of what fine-tuning bought can be recovered
for free: re-rank the retrieved text down to the single most relevant
sentence, paste that sentence at the very top of the prompt as a hint, and
the un-fine-tuned model beats the fine-tuned one.

## Key patterns & decisions
- **Retrieval is the default knowledge-injection mechanism; fine-tuning is
  the expensive fallback.** Across all twelve models, adding retrieved
  context moved accuracy far more than fine-tuning did — e.g. StableLM2
  (1.6B) on PopQA went from 17.01 vanilla to 76.14 with retrieval, versus
  21.75 with fine-tuning alone. Budget engineering effort accordingly.
- **The rarer the fact, the bigger retrieval's edge.** Accuracy was broken
  out over five entity-popularity buckets (log pageviews); retrieval's gain
  is largest in the least-popular bucket. For popular entities the model
  already knows the answer and retrieval adds little.
- **Fine-tuning helps small models and hurts big ones in a RAG pipeline.**
  Combining fine-tuning with retrieval was best for models up to about 3B
  parameters, but degraded 7B–11.3B models. Do not assume a domain
  fine-tune is a free additive win on top of your retrieval stack.
- **If you must fine-tune, prefer parameter-efficient tuning over full
  tuning when the model will later be used with retrieval.** Full tuning
  scored better without retrieval, but PEFT (QLoRA) scored better with it —
  full tuning collapsed a StableLM2 run to 5.87 accuracy on PopQA+RAG,
  which reads as destroyed in-context reasoning rather than lost facts.
- **Synthetic training-data quality dominates quantity.** The end-to-end
  QA generator produced over 12x more pairs than prompting a capable
  instruct model with a chain-of-thought template, yet the prompt-generated
  data trained consistently better models. Generating fewer, better
  examples is the right call.
- **Retriever quality is the RAG system's ceiling.** Recall@1 on PopQA
  ranged from 40.13 (BM25) to 59.40 (DPR), and downstream answer accuracy
  tracked retriever quality directly. Upgrading the retriever is usually a
  cheaper accuracy lever than touching the generator.
- **More retrieved documents is not monotonically better.** Going from one
  to three documents gave a clear jump; going to five gave negligible gain
  or a regression, even though recall@5 exceeded recall@3. Extra context
  becomes noise the model must filter.
- **Position matters — put the strongest evidence first.** The proposed
  Stimulus RAG splits the top-3 documents into sentences, re-ranks them
  against the query, and prepends the single best sentence (or its parent
  document) as an explicit hint. No new information enters the prompt; only
  its ordering and salience change, and accuracy exceeds the fine-tuned
  plus retrieval configuration in every case reported.
- **A small model with good retrieval can substitute for a large one.** The
  best fine-tuned-plus-retrieval result came from a 1.6B model, matching or
  beating 7B–8B models — a real cost lever for serving.

## When to apply / trade-offs
Apply this when you are deciding how to make an LLM feature answer
questions about knowledge that is specific to your organisation or domain
and is unlikely to be well represented in pre-training. The default
sequencing it argues for is: build retrieval first, invest in retriever
quality and in re-ranking down to the most relevant span, cap the context
at roughly the top three documents, and only consider fine-tuning if
retrieval genuinely cannot reach the required accuracy — and then only for
small models, using parameter-efficient methods. The costs are real: you
now own an index, an embedding/retrieval service, and a re-ranking hop
that adds latency, and retrieved content is untrusted input that must be
fenced against prompt injection. The findings are also scoped narrowly —
short factual triple-style questions, substring-match accuracy scoring
(which the authors themselves flag as brittle for dates and partial-name
matches), Wikipedia-derived corpora, and models no larger than 11.3B. Do
not extrapolate to multi-hop reasoning, long-form generation, style or
format adaptation, or frontier-scale models; fine-tuning remains the right
tool for teaching behaviour and output shape rather than facts.

## Fidelity check
1. Claim: retrieval outperforms fine-tuning by a large margin, most so for
   the least popular knowledge. Support: the capture states that RAG
   surpasses FT by a large margin particularly for least popular factual
   knowledge, and reports RAG significantly increasing accuracy for the
   least popular entity buckets.
2. Claim: fine-tuning combined with retrieval helps models up to ~3B and
   degrades 7B–11.3B models. Support: the capture states that combining FT
   with RAG yields the best results for smaller models up to 3B parameters
   while degrading performance for models from 7B to 11.3B, attributing it
   to diminished reasoning ability.
3. Claim: the hint is prepended and draws on attention to the prompt start,
   and SRAG beats fine-tuned RAG without adding information. Support: the
   capture reports that the extracted hint is placed at the top of the
   prompt citing evidence that the beginning receives more attention, that
   the hint is derived from the same top-3 documents so no extra
   information is added, and that SRAG without FT beats fine-tuned LMs with
   top-3 RAG in all cases.
