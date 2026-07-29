# rag-and-model-tuning

Knowledge injection for LLM features — deciding between retrieval and training, then building either one well.

## What this covers

- **The retrieve-vs-tune decision** — the adaptation ladder walked top-down, what fine-tuning cannot do (no freshness, no citations, no per-user access control), and the measured finding that retrieval beats tuning for long-tail facts and wins hardest where the fact is rarest
- **Chunking as a retrieval decision** — why fixed-size splitting orphans tables, code, and clauses; hierarchical versus semantic strategies by corpus shape; chunk configuration as a versioned artifact that invalidates caches and eval baselines
- **Hybrid retrieval** — the three blind spots of pure vector search (exact identifiers, precise jargon, recency), running dense and lexical engines in parallel, and choosing between weighted score combination, reciprocal rank fusion, and a learned fusion model
- **Reranking with a stop rule** — cross-encoder joint scoring as a second-stage precision filter, explicit add and remove thresholds, latency/cost bands by reranker category, minimum relevance thresholds that permit refusal, and deterministic context packing
- **Multi-tenant retrieval safety** — filtering before the similarity search rather than after, failing closed when tenant context is missing, and mirroring isolation onto the lexical index
- **Retrieval evaluation** — the RAG triad (context relevance, faithfulness, answer relevance), context precision and recall, faithfulness by claim decomposition, why n-gram overlap metrics are unfit, and why recall can hold while ranking quality collapses
- **Fine-tuning mechanics** — PEFT over full tuning, LoRA rank and alpha, adapters versus merged weights, quantized tuning as a memory trade, retrieval-aware tuning, and the imitation-data failure mode
- **Distillation** — curated behavior cloning scored on cost per success, self-distillation for knowledge injection, distilling demonstrations into an editable text cheat sheet, router deployment with an escalation path, and mandatory drift surveillance
- **Operating the pipeline** — degraded modes, index snapshots and rollback, sharding and stage decoupling, storage arithmetic, and the corpus size below which long context plus prompt caching wins outright

## Origin

Synthesized from own-words digests of ten public articles and papers on RAG architecture, retrieval evaluation, fine-tuning, and distillation. Each digest carries its own source attribution and a fidelity check against the original; no verbatim text is reproduced. Tool and vendor names that appear in the digests are treated as examples of categories, never as recommendations.

## Structure

- `SKILL.md` — the full skill: the retrieve-vs-tune decision, core conventions, anti-patterns, and cross-links
- `references/aie-059-distillation-with-programmatic-data-curation-cheaper-infer.md` — curated behavior cloning, cost per success, reliability at k, per-policy distillation
- `references/aie-060-efficient-knowledge-injection-in-llms-via-self-distillatio.md` — self-distillation for knowledge injection, soft targets, forgetting penalty, stacking with retrieval
- `references/aie-061-distilling-many-shot-in-context-learning-into-a-cheat-shee.md` — distilling demonstrations into an editable text artifact, accuracy per input token
- `references/aie-062-llm-fine-tuning-customize-large-language-models.md` — the adaptation ladder, full tuning versus PEFT, LoRA, adapters, quantized tuning
- `references/aie-063-the-architects-guide-to-production-rag.md` — the production failure surface, chunking strategies, query decomposition, reranking, caching, sharding
- `references/aie-064-rag-best-practices-chunking-hybrid-search-reranking.md` — vector blind spots, fusion strategies, reranker thresholds, filter-before-search, observability
- `references/aie-065-fine-tuning-vs-retrieval-augmented-generation-for-less-pop.md` — the head-to-head comparison on long-tail knowledge, model-size interaction, the prepended-hint result
- `references/aie-067-building-production-grade-rag-architecture-the-engineering.md` — permissions in candidate generation, refusal thresholds, deterministic packing, evidence-based golden sets
- `references/aie-068-best-rag-tools-frameworks-and-libraries.md` — component quality versus size and price, engines as an ops choice, recall/nDCG divergence, RAG versus long context
- `references/aie-069-rag-evaluation-metrics.md` — the RAG triad, claim decomposition, eval-set sizing and stratification, release gates

## Usage

Read this skill when a model needs knowledge it does not have — before choosing between an index and a training run, when a retrieval pipeline answers confidently but wrongly, when a reranker or a fine-tune is being proposed without a measured trigger, or when a retrieval system needs an evaluation harness that can attribute a regression to a specific subsystem.

## Cross-references

- **`.claude/rules/agent-guardrails.md`** (always loaded) — prompt-injection defense for untrusted content, including retrieved passages. This skill defers to it and adds only what is retrieval-specific, namely that an index makes an injection persistent across every future query.
- **`.claude/rules/evals.md`** (always loaded) — general eval discipline: eval-set-first, grader choice, LLM-as-judge calibration, regression gating. The RAG triad is a decomposition layered on top of that rule, not a replacement for it.
- **context-engineering** — prompt construction and context-window budgeting; owns what goes in the system prompt versus the retrieved payload.
- **langfuse-llm-tracing** — LLM trace plumbing, token accounting, and cost analytics; the substrate that retrieval observability and continuous production evaluation sit on.
- **security-and-hardening** — broader application and LLM-feature security, including the input/output guardrail chain around the model boundary.
- **performance-optimization** — general latency and cost framing for the budgets this skill spends on reranking, query fan-out, and index hosting.

## Key distinction from adjacent skills

This skill owns **knowledge injection** — getting facts the model lacks into an answer, and measuring whether that worked:

- **rag-and-model-tuning** → retrieve or train, chunking, hybrid search, reranking, retrieval evals, LoRA, distillation
- **context-engineering** → what to put in the prompt and how to budget the window
- **langfuse-llm-tracing** → instrumenting and observing the calls
- **security-and-hardening** → guarding the model boundary
- **`.claude/rules/evals.md`** → how to build and gate on a graded eval set at all
