# AI-engineering articles — coverage map

Source: a reading list of 72 AI-engineering URLs supplied directly by the maintainer on 2026-07-28
(articles © their respective publishers). Fetched via a browser User-Agent; five hosts refuse
automated clients and one sits behind a Cloudflare challenge — those are honest "not fetched" rows,
never bypassed. Ideas absorbed in the kit's own words with attribution; no text or code reproduced
(see `docs/influences.md`). Digests are named `aie-*.md`, numbered by this map's global row index.

Digests for **agent-operation** topics ship into the owning skill's `references/`. Digests for
**LLM-application engineering** (quantization, KV cache, caching, RAG, gateways, provider failover)
ship into four new **stack-collection skills** — `llm-inference-optimization`,
`llm-caching-strategies`, `rag-and-model-tuning`, and `llm-gateway-and-routing`. That material is
stack-specific domain knowledge, and golden rule #1 keeps it out of the stack-agnostic core; the
collection is where such knowledge already lives, so no `catalog/stacks.yaml` change was needed.

## Harness engineering

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Harness Engineering for LLM Agents: A Survey](https://openreview.net/forum?id=1VJLY0hAFT) | no | — | not fetched (cloudflare challenge) — honest row, no digest |
| 2 | [What is an AI Agent Harness?](https://www.databricks.com/blog/ai-harness) | yes | `skills/context-engineering/references/aie-002-what-is-an-ai-agent-harness.md` | reference digest in `context-engineering` |
| 3 | [Harness Engineering as Categorical Architecture: Structural Guarantees Are Harness-Level Properties](https://arxiv.org/html/2605.12239v1) | yes | `skills/context-engineering/references/aie-003-harness-engineering-as-categorical-architecture.md` | reference digest in `context-engineering` |
| 4 | [Harness Engineering: The Missing Layer Between LLMs and Production Systems](https://ranjankumar.in/harness-engineering-the-missing-layer-between-llms-and-production-systems) | yes | `skills/context-engineering/references/aie-004-harness-engineering-the-missing-layer-between-llms-and-pro.md` | reference digest in `context-engineering` |
| 5 | [A lot of conversation around Harness Engineering, what does that even mean? (Reddit r/AI_Agents)](https://www.reddit.com/r/AI_Agents/comments/1ujigq2/a_lot_of_conversation_around_harness_engineering/) | yes | `skills/context-engineering/references/aie-005-a-lot-of-conversation-around-harness-engineering-what-does.md` | reference digest in `context-engineering` |
| 6 | [Harness Engineering for LLM Agents: A Survey (preprints.org)](https://www.preprints.org/manuscript/202606.2203) | no | — | deduplicated — duplicate of the OpenReview row above (same survey) |

## Context engineering vs prompt engineering

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Context engineering vs. prompt engineering](https://www.elastic.co/search-labs/blog/context-engineering-vs-prompt-engineering) | yes | `skills/context-engineering/references/aie-007-context-engineering-vs-prompt-engineering-elastic.md` | reference digest in `context-engineering` |
| 2 | [Context engineering vs prompt engineering: the difference](https://redis.io/blog/context-engineering-vs-prompt-engineering/) | yes | `skills/context-engineering/references/aie-008-context-engineering-vs-prompt-engineering-the-difference-r.md` | reference digest in `context-engineering` |
| 3 | [Context engineering vs prompt engineering: key differences explained](https://www.glean.com/perspectives/context-engineering-vs-prompt-engineering-key-differences-explained) | yes | `skills/context-engineering/references/aie-009-context-engineering-vs-prompt-engineering-key-differences.md` | reference digest in `context-engineering` |
| 4 | [Context Engineering vs Prompt Engineering (DataHub)](https://datahub.com/blog/context-engineering-vs-prompt-engineering/) | yes | `skills/context-engineering/references/aie-010-context-engineering-vs-prompt-engineering-datahub.md` | reference digest in `context-engineering` |
| 5 | [Context Engineering vs Prompt Engineering (Abstracta)](https://abstracta.us/blog/ai/context-engineering-vs-prompt-engineering) | yes | `skills/context-engineering/references/aie-011-context-engineering-vs-prompt-engineering-abstracta.md` | reference digest in `context-engineering` |

## LLM and agent observability

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [OpenTelemetry for AI Observability: What It Covers and Where It Stops](https://www.fiddler.ai/blog/opentelemetry-ai-observability-guide) | yes | `skills/langfuse-llm-tracing/references/aie-012-opentelemetry-for-ai-observability-what-it-covers-and-wher.md` | reference digest in `langfuse-llm-tracing` |
| 2 | [OpenTelemetry for LLMs: how we instrument a multi-provider AI gateway](https://www.truefoundry.com/blog/opentelemetry-llm-gateway-instrumentation) | yes | `skills/langfuse-llm-tracing/references/aie-013-opentelemetry-for-llms-instrumenting-a-multi-provider-ai-g.md` | reference digest in `langfuse-llm-tracing` |
| 3 | [4 best LLM gateways for observability: tracing, cost attribution, and debuggability](https://www.braintrust.dev/articles/best-llm-gateways-observability-2026) | yes | `skills/langfuse-llm-tracing/references/aie-014-best-llm-gateways-for-observability-tracing-cost-attributi.md` | reference digest in `langfuse-llm-tracing` |
| 4 | [LLM Observability with OpenTelemetry — unified AI application tracing guide](https://docs.base14.io/guides/ai-observability/llm-observability/) | yes | `skills/langfuse-llm-tracing/references/aie-015-llm-observability-with-opentelemetry-unified-tracing-guide.md` | reference digest in `langfuse-llm-tracing` |
| 5 | [LLM Observability (glossary)](https://www.guild.ai/glossary/llm-observability) | yes | `skills/langfuse-llm-tracing/references/aie-016-llm-observability-glossary.md` | reference digest in `langfuse-llm-tracing` |
| 6 | [The 2026 Guide To Agent Observability Tools](https://montecarlo.ai/blog-agent-observability-tools) | yes | `skills/langfuse-llm-tracing/references/aie-017-the-2026-guide-to-agent-observability-tools.md` | reference digest in `langfuse-llm-tracing` |

## Model routing, failover and gateways

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [LLM routing in production: choosing the right model for every request](https://blog.logrocket.com/llm-routing-right-model-for-requests/) | yes | `skills/llm-gateway-and-routing/references/aie-018-llm-routing-in-production-choosing-the-right-model-for-eve.md` | reference digest in `llm-gateway-and-routing` |
| 2 | [LLM Failover & Load Balancing for Provider Outages](https://www.truefoundry.com/blog/llm-failover-load-balancing-provider-outages) | yes | `skills/llm-gateway-and-routing/references/aie-019-llm-failover-and-load-balancing-for-provider-outages.md` | reference digest in `llm-gateway-and-routing` |
| 3 | [Adaptive Model Routing and Fallback Logic: routing around LLM provider outages with Bifrost](https://dev.to/kuldeep_paul/adaptive-model-routing-and-fallback-logic-routing-around-llm-provider-outages-with-bifrost-4g3m) | yes | `skills/llm-gateway-and-routing/references/aie-020-adaptive-model-routing-and-fallback-logic-routing-around-p.md` | reference digest in `llm-gateway-and-routing` |
| 4 | [Build an LLM Fallback Layer Before Your Model Vanishes](https://theroadtoenterprise.com/blog/model-agnostic-ai-layer-fallbacks) | yes | `skills/llm-gateway-and-routing/references/aie-021-build-an-llm-fallback-layer-before-your-model-vanishes.md` | reference digest in `llm-gateway-and-routing` |
| 5 | [Three-Tier LLM Routing: Fast, Smart, and Power Model Stacks](https://www.mindstudio.ai/blog/set-up-ai-model-router-llm-stack-c2610) | yes | `skills/llm-gateway-and-routing/references/aie-022-three-tier-llm-routing-fast-smart-and-power-model-stacks.md` | reference digest in `llm-gateway-and-routing` |
| 6 | [What our provider fallback actually looks like after a few months in prod (Reddit r/LLMDevs)](https://www.reddit.com/r/LLMDevs/comments/1ulbef7/what_our_provider_fallback_actually_looks_like/) | yes | `skills/llm-gateway-and-routing/references/aie-023-what-our-provider-fallback-actually-looks-like-after-month.md` | reference digest in `llm-gateway-and-routing` |

## Agent and MCP security

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Security Best Practices (Model Context Protocol, official)](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices) | yes | `skills/security-and-hardening/references/aie-024-model-context-protocol-security-best-practices.md` | reference digest in `security-and-hardening` |
| 2 | [Systematization of Knowledge: Security and Safety in the Model Context Protocol Ecosystem](https://arxiv.org/html/2512.08290v2) | yes | `skills/threat-model/references/aie-025-sok-security-and-safety-in-the-model-context-protocol-ecos.md` | reference digest in `threat-model` |
| 3 | [Prompt Injection in Production Agents: 2026 Taxonomy](https://www.digitalapplied.com/blog/prompt-injection-production-agents-2026-taxonomy) | yes | `skills/security-and-hardening/references/aie-026-prompt-injection-in-production-agents-a-2026-taxonomy.md` | reference digest in `security-and-hardening` |
| 4 | [Model Context Protocol: Security Risks & Mitigations](https://socprime.com/blog/mcp-security-risks-and-mitigations/) | yes | `skills/security-and-hardening/references/aie-027-model-context-protocol-security-risks-and-mitigations.md` | reference digest in `security-and-hardening` |
| 5 | [AI Agent Data Leakage: Secrets Management and Privacy Risks](https://rafter.so/blog/ai-agent-data-leakage-secrets-management) | yes | `skills/security-and-hardening/references/aie-028-ai-agent-data-leakage-secrets-management-and-privacy-risks.md` | reference digest in `security-and-hardening` |
| 6 | [Multi-tenant isolation for AI agents: security architecture guide](https://blaxel.ai/blog/multi-tenant-isolation-ai-agents) | yes | `skills/multi-tenancy-patterns/references/aie-029-multi-tenant-isolation-for-ai-agents-security-architecture.md` | reference digest in `multi-tenancy-patterns` |
| 7 | [LLM Security — Prompt Injection, Data Leakage & Compliance (2026)](https://myengineeringpath.dev/genai-engineer/llm-security/) | yes | `skills/security-and-hardening/references/aie-030-llm-security-prompt-injection-data-leakage-and-compliance.md` | reference digest in `security-and-hardening` |
| 8 | [Model Context Protocol (MCP): Security Design Considerations for AI-Driven Automation (CSI)](https://media.defense.gov/2026/Jun/02/2003943289/-1/-1/0/CSI_MCP_SECURITY.PDF) | no | — | not fetched (http=403) — honest row, no digest |

## Structured outputs

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [LLM Structured Outputs: Schema Validation for Real Pipelines (2026)](https://collinwilkins.com/articles/structured-output) | yes | `skills/llm-gateway-and-routing/references/aie-032-llm-structured-outputs-schema-validation-for-real-pipeline.md` | reference digest in `llm-gateway-and-routing` |
| 2 | [guidance-ai/llguidance: super-fast structured outputs](https://github.com/guidance-ai/llguidance) | yes | `skills/llm-gateway-and-routing/references/aie-033-llguidance-super-fast-structured-outputs.md` | reference digest in `llm-gateway-and-routing` |

## Agent failure attribution

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [REFLECT: Intervention-Supported Error Attribution for Silent Failures in LLM Agent Traces](https://arxiv.org/html/2606.09071v1) | yes | `skills/debugging-and-error-recovery/references/aie-034-reflect-intervention-supported-error-attribution-for-silen.md` | reference digest in `debugging-and-error-recovery` |

## Multi-agent architecture

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [How I Built an AI Agent Architecture — a practical multi-agent LLM for newsletter generation](https://thomasthelliez.com/blog/how-i-built-an-ai-agent-architecture/) | yes | `skills/context-engineering/references/aie-035-how-i-built-an-ai-agent-architecture-a-practical-multi-age.md` | reference digest in `context-engineering` |

## Quantization

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Accelerating LLM inference with post-training weight and activation quantization using AWQ and GPTQ on Amazon SageMaker AI](https://aws.amazon.com/blogs/machine-learning/accelerating-llm-inference-with-post-training-weight-and-activation-using-awq-and-gptq-on-amazon-sagemaker-ai/) | yes | `skills/llm-inference-optimization/references/aie-038-accelerating-llm-inference-with-post-training-quantization.md` | reference digest in `llm-inference-optimization` |
| 2 | [LLM Quantization Explained: INT4, INT8, FP8, AWQ, and GPTQ in 2026](https://vrlatech.com/llm-quantization-explained-int4-int8-fp8-awq-and-gptq-in-2026/) | yes | `skills/llm-inference-optimization/references/aie-039-llm-quantization-explained-int4-int8-fp8-awq-and-gptq.md` | reference digest in `llm-inference-optimization` |
| 3 | [LLM Quantization: BF16 vs FP8 vs INT4](https://aimultiple.com/llm-quantization) | yes | `skills/llm-inference-optimization/references/aie-040-llm-quantization-bf16-vs-fp8-vs-int4.md` | reference digest in `llm-inference-optimization` |

## Speculative decoding

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Faster, cheaper, just as smart: improving the economics of LLM inference with speculative decoding](https://www.redhat.com/en/blog/solving-economics-llm-inference-speculative-decoding) | yes | `skills/llm-inference-optimization/references/aie-041-improving-the-economics-of-llm-inference-with-speculative.md` | reference digest in `llm-inference-optimization` |
| 2 | [Speculative Decoding, Quantization, and Distillation Tradeoffs](https://redpumpkin.ai/blog/speculative-decoding-quantization-and-distillation-tradeoffs) | yes | `skills/llm-inference-optimization/references/aie-042-speculative-decoding-quantization-and-distillation-tradeof.md` | reference digest in `llm-inference-optimization` |
| 3 | [Speculative Decoding and Quantization — LLM Inference](https://theorempath.com/topics/speculative-decoding-and-quantization) | yes | `skills/llm-inference-optimization/references/aie-043-speculative-decoding-and-quantization-llm-inference.md` | reference digest in `llm-inference-optimization` |

## Prefill vs decode

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Prefill and Decode: a technical guide to the two phases of inference](https://www.weka.io/learn/ai-ml/prefill-and-decode/) | yes | `skills/llm-inference-optimization/references/aie-044-prefill-and-decode-a-technical-guide-to-the-two-phases-of.md` | reference digest in `llm-inference-optimization` |
| 2 | [Prefill vs Decode: LLM inference phases explained](https://redis.io/blog/prefill-vs-decode/) | yes | `skills/llm-inference-optimization/references/aie-045-prefill-vs-decode-llm-inference-phases-explained.md` | reference digest in `llm-inference-optimization` |
| 3 | [Prefill vs Decode: LLM Inference Optimization (Outcome School)](https://outcomeschool.com/blog/prefill-vs-decode-llm-inference-optimization) | yes | `skills/llm-inference-optimization/references/aie-046-prefill-vs-decode-llm-inference-optimization.md` | reference digest in `llm-inference-optimization` |
| 4 | [LLM Inference Optimization — Prefill vs Decode (Towards AI)](https://pub.towardsai.net/llm-inference-optimization-prefill-vs-decode-6e003d48b2ca) | yes | `skills/llm-inference-optimization/references/aie-047-llm-inference-optimization-prefill-vs-decode.md` | reference digest in `llm-inference-optimization` |
| 5 | [The LLM Inference Optimization Stack: quantization to speculative decoding, part 1](https://www.digitalocean.com/community/tutorials/llm-inference-optimization-stack-part-1) | yes | `skills/llm-inference-optimization/references/aie-048-the-llm-inference-optimization-stack-quantization-to-specu.md` | reference digest in `llm-inference-optimization` |

## KV cache management

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Automatic Prefix Caching — design (vLLM docs)](https://docs.vllm.ai/en/stable/design/prefix_caching/) | yes | `skills/llm-inference-optimization/references/aie-049-automatic-prefix-caching-design-in-vllm.md` | reference digest in `llm-inference-optimization` |
| 2 | [PEEK: Predictive Queue-Informed KV Cache Management for LLM Serving](https://arxiv.org/html/2607.02525v1) | yes | `skills/llm-inference-optimization/references/aie-050-peek-predictive-queue-informed-kv-cache-management-for-llm.md` | reference digest in `llm-inference-optimization` |
| 3 | [EpiCache: Episodic KV Cache Management for Long-Term Conversation on Resource-Constrained Environments](https://icml.cc/virtual/2026/poster/65405) | yes | `skills/llm-inference-optimization/references/aie-051-epicache-episodic-kv-cache-management-for-long-term-conver.md` | reference digest in `llm-inference-optimization` |
| 4 | [Automatic Prefix Caching — implementation details (vLLM v0.6.2)](https://docs.vllm.ai/en/v0.6.2/automatic_prefix_caching/details.html) | yes | `skills/llm-inference-optimization/references/aie-052-automatic-prefix-caching-implementation-details-vllm.md` | reference digest in `llm-inference-optimization` |
| 5 | [Understanding vLLM KV cache (forum thread)](https://discuss.vllm.ai/t/understanding-vllm-kv-cache/2061) | yes | `skills/llm-inference-optimization/references/aie-053-understanding-vllm-kv-cache.md` | reference digest in `llm-inference-optimization` |

## Prompt and semantic caching

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Prompt caching vs semantic caching: how to make AI agents faster](https://redis.io/blog/prompt-caching-vs-semantic-caching/) | yes | `skills/llm-caching-strategies/references/aie-054-prompt-caching-vs-semantic-caching-how-to-make-ai-agents-f.md` | reference digest in `llm-caching-strategies` |
| 2 | [The Cache Has Layers: prompt caching, semantic caching, and when each one betrays you](https://acethecloud.com/blog/prompt-caching-semantic-caching-tradeoffs/) | yes | `skills/llm-caching-strategies/references/aie-055-the-cache-has-layers-prompt-caching-semantic-caching-and-w.md` | reference digest in `llm-caching-strategies` |
| 3 | [Prompt Caching in 2026: cut LLM costs, keep quality](https://www.digitalapplied.com/blog/prompt-caching-2026-cut-llm-costs-engineering-guide) | yes | `skills/llm-caching-strategies/references/aie-056-prompt-caching-cut-llm-costs-keep-quality.md` | reference digest in `llm-caching-strategies` |
| 4 | [Semantic Caching: boost LLM speed & reduce costs](https://www.truefoundry.com/blog/semantic-caching) | yes | `skills/llm-caching-strategies/references/aie-057-semantic-caching-boost-llm-speed-and-reduce-costs.md` | reference digest in `llm-caching-strategies` |
| 5 | [Optimize LLM response costs and latency with effective caching](https://aws.amazon.com/blogs/database/optimize-llm-response-costs-and-latency-with-effective-caching/) | yes | `skills/llm-caching-strategies/references/aie-058-optimize-llm-response-costs-and-latency-with-effective-cac.md` | reference digest in `llm-caching-strategies` |

## Distillation and fine-tuning

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Distillation with Programmatic Data Curation: smarter LLMs, 5-30x cheaper inference](https://www.tensorzero.com/blog/distillation-programmatic-data-curation-smarter-llms-5-30x-cheaper-inference/) | yes | `skills/rag-and-model-tuning/references/aie-059-distillation-with-programmatic-data-curation-cheaper-infer.md` | reference digest in `rag-and-model-tuning` |
| 2 | [Efficient Knowledge Injection in LLMs via Self-Distillation](https://arxiv.org/html/2412.14964v2) | yes | `skills/rag-and-model-tuning/references/aie-060-efficient-knowledge-injection-in-llms-via-self-distillatio.md` | reference digest in `rag-and-model-tuning` |
| 3 | [Distilling Many-Shot In-Context Learning into a Cheat Sheet (ACL Findings EMNLP 2025)](https://aclanthology.org/2025.findings-emnlp.930.pdf) | yes | `skills/rag-and-model-tuning/references/aie-061-distilling-many-shot-in-context-learning-into-a-cheat-shee.md` | reference digest in `rag-and-model-tuning` |
| 4 | [LLM Fine-tuning: customize large language models](https://billtcheng2013.medium.com/llm-fine-tuning-7986bb8e939f) | yes | `skills/rag-and-model-tuning/references/aie-062-llm-fine-tuning-customize-large-language-models.md` | reference digest in `rag-and-model-tuning` |

## Retrieval-augmented generation

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [The Architect's Guide to Production RAG: navigating challenges and building scalable AI](https://www.ragie.ai/blog/the-architects-guide-to-production-rag-navigating-challenges-and-building-scalable-ai) | yes | `skills/rag-and-model-tuning/references/aie-063-the-architects-guide-to-production-rag.md` | reference digest in `rag-and-model-tuning` |
| 2 | [RAG Best Practices: chunking, hybrid search, reranking](https://codewheel.ai/blog/rag-architecture-guide/) | yes | `skills/rag-and-model-tuning/references/aie-064-rag-best-practices-chunking-hybrid-search-reranking.md` | reference digest in `rag-and-model-tuning` |
| 3 | [Fine Tuning vs. Retrieval Augmented Generation for Less Popular Knowledge (v3)](https://arxiv.org/html/2403.01432v3) | yes | `skills/rag-and-model-tuning/references/aie-065-fine-tuning-vs-retrieval-augmented-generation-for-less-pop.md` | reference digest in `rag-and-model-tuning` |
| 4 | [Fine Tuning vs. Retrieval Augmented Generation for Less Popular Knowledge (v1)](https://arxiv.org/html/2403.01432v1) | yes | — | deduplicated — duplicate of `aie-065` (same paper, v3) |
| 5 | [Building Production-Grade RAG Architecture: the engineering playbook](https://www.cloudaeon.com/insights/building-production-grade-rag-architecture:-the-engineering-playbook) | yes | `skills/rag-and-model-tuning/references/aie-067-building-production-grade-rag-architecture-the-engineering.md` | reference digest in `rag-and-model-tuning` |
| 6 | [Best RAG Tools, Frameworks, and Libraries](https://aimultiple.com/retrieval-augmented-generation) | yes | `skills/rag-and-model-tuning/references/aie-068-best-rag-tools-frameworks-and-libraries.md` | reference digest in `rag-and-model-tuning` |
| 7 | [RAG Evaluation Metrics: improve RAG](https://customgpt.ai/rag-evaluation-metrics/) | yes | `skills/rag-and-model-tuning/references/aie-069-rag-evaluation-metrics.md` | reference digest in `rag-and-model-tuning` |
| 8 | [RAG Evaluation Metrics: answer relevancy, faithfulness, and real-world accuracy](https://deepchecks.com/rag-evaluation-metrics-answer-relevancy-faithfulness-accuracy/) | no | — | not fetched (http=403) — honest row, no digest |
| 9 | [RAG Framework Explained for Enterprise AI and LLMs](https://tblocks.com/guides/rag-framework/) | no | — | not fetched (http=403) — honest row, no digest |
| 10 | [Building a Security and Reliability Evaluation Suite for Retrieval-Augmented Generation (RAG) Systems](https://www.preprints.org/manuscript/202510.0418/v1) | no | — | not fetched (http=403) — honest row, no digest |

## Not articles

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [AI Insights Archives (category index page)](https://sudoall.com/category/ai-insights/) | yes | — | not absorbed — index page, not an article |
| 2 | [David Saliba, Author at SudoAll (author index page)](https://sudoall.com/author/admin/) | yes | — | not absorbed — index page, not an article |

---

*72 items noted; 63 shipped digests — 24 into six existing skills, 39 into four new stack-collection skills.*
