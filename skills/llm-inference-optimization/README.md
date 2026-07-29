# llm-inference-optimization

Serving-side performance and cost engineering for self-hosted LLMs — quantization, pruning, speculative decoding, batching, and KV-cache reuse, chosen by whether the workload is prefill-bound or decode-bound.

## What this covers

- **The prefill/decode split** — why one request is two workloads with opposite hardware profiles (compute-bound prefill, memory-bandwidth-bound decode), and why a single "latency" number hides which one is failing
- **Per-phase metrics** — TTFT, inter-token latency, the `TTFT + (N−1)×TPOT` identity, tail latency in agentic chains, and defensible SLO thresholds
- **Capacity arithmetic** — bytes-per-parameter sizing, KV-cache overhead, and why quantization's real payoff is usually concurrency rather than speed
- **Quantization** — the WxAy notation, FP8/INT8/INT4/GGUF format trade-offs, AWQ vs GPTQ vs SmoothQuant, calibration-set provenance, and the PTQ→dynamic→static→QAT ladder
- **Task-shaped accuracy loss** — where the sources disagree, why aggregate retention percentages understate damage to code generation and reasoning, and what the eval gate has to look like
- **Pruning** — structured vs unstructured (and why only one of them speeds up a dense GPU), hardware sparsity patterns, and named methods
- **Speculative decoding** — acceptance length as the governing metric, the workloads where it pays, the workloads where it is a pessimization, and how it composes with quantization
- **Batching and memory layout** — continuous batching, PagedAttention, efficient attention kernels, and batch size as the latency/throughput knob
- **KV cache and prefix caching** — block-identity hashing, prompt layout for cache hits, peak vs steady-state memory, and episodic compression for long conversations
- **Cache keys as a security boundary** — LoRA IDs, multimodal hashes, per-tenant cache salts, and the timing side channel in shared serving
- **Scheduling** — admission ordering dominating eviction policy, scheduling-induced thrashing, fairness lanes, chunked prefill, and disaggregated serving
- **Measurement discipline** — isolation before attribution, the pre-allocated-KV-pool debugging trap, the profiling tool ladder, and the six evaluation axes

## Derived from public sources

The reference digests are own-words summaries of public articles, vendor documentation, and research papers on LLM inference. Each digest's frontmatter names its source and author, and no source text or code is reproduced. Several sources are vendor-authored; the skill flags those inline where the framing is self-interested, and it states explicitly where sources conflict rather than silently picking one.

## Structure

- `SKILL.md` — Full guide with usage triggers, per-technique conventions, decision criteria, and anti-patterns
- `references/aie-038-accelerating-llm-inference-with-post-training-quantization.md` — WxAy notation, AWQ/GPTQ/SmoothQuant, measured memory, latency and throughput across concurrency 1–128
- `references/aie-039-llm-quantization-explained-int4-int8-fp8-awq-and-gptq.md` — bytes-per-parameter sizing, format vs method, aggregate retention figures, GGUF, QLoRA/NF4
- `references/aie-040-llm-quantization-bf16-vs-fp8-vs-int4.md` — task-shaped accuracy loss and the concurrency payoff of freed weight memory
- `references/aie-041-improving-the-economics-of-llm-inference-with-speculative.md` — speculator/verifier roles, acceptance length, coding vs summarization case study
- `references/aie-042-speculative-decoding-quantization-and-distillation-tradeof.md` — bottleneck-first technique selection, distillation as a model-product decision, six evaluation axes
- `references/aie-043-speculative-decoding-and-quantization-llm-inference.md` — losslessness as a distribution property, quantized-target/full-precision-draft default
- `references/aie-044-prefill-and-decode-a-technical-guide-to-the-two-phases-of.md` — the phase split, arithmetic intensity, perceptual thresholds, disaggregated serving, chunked prefill
- `references/aie-045-prefill-vs-decode-llm-inference-phases-explained.md` — ITL derivation, workload-shape mapping, phase contention, prefix vs semantic caching
- `references/aie-046-prefill-vs-decode-llm-inference-optimization.md` — the end-to-end latency formula, continuous batching, PagedAttention vs prefix caching
- `references/aie-047-llm-inference-optimization-prefill-vs-decode.md` — per-phase measurement, the pre-allocated-KV-pool trap, tensor-parallel decode collectives
- `references/aie-048-the-llm-inference-optimization-stack-quantization-to-specu.md` — structured vs unstructured pruning, sparsity patterns, PTQ ladder, mixed precision
- `references/aie-049-automatic-prefix-caching-design-in-vllm.md` — chained block hash, extra-hash extension point, cache salt, hash-algorithm security axis
- `references/aie-050-peek-predictive-queue-informed-kv-cache-management-for-llm.md` — the pending queue as a demand signal, admission ordering vs eviction, fairness lanes
- `references/aie-051-epicache-episodic-kv-cache-management-for-long-term-conver.md` — peak-memory budgeting, block-wise prefill, episodic compression, multi-turn eviction traps
- `references/aie-052-automatic-prefix-caching-implementation-details-vllm.md` — the block-identity claim behind flat-hash prefix reuse, LoRA-in-the-hash, default eviction
- `references/aie-053-understanding-vllm-kv-cache.md` — scheduler call sequence, block pool vs memory pool, assignment vs tensor write

## Usage

Reference this skill when:

- Sizing or re-sizing GPUs for a self-hosted model
- Choosing a precision format or quantization method before a deploy
- Triaging a slow generation endpoint into a prefill or decode problem
- Designing prompt layout and cache-key isolation for prefix caching
- Reviewing an inference-cost proposal that stacks several techniques at once

## Cross-references

- **performance-optimization** — general service profiling and hot-path work. Use it for the portion of request time spent outside the model.
- **load-testing** — generating the realistic sustained concurrency that any capacity claim in this skill depends on.
- **redis-caching-patterns** — the application-level cache tier above the model (exact-match and semantic response caching, invalidation, stampede protection). Complements prefix caching; does not replace it.
- **langfuse-llm-tracing** — per-call LLM telemetry: latency, token usage, cost attribution, model and provider labelling.
- **observability-and-logging** — dashboards, SLOs, and alerting for the serving tier as a whole.

## Scope boundary

This skill is about the inference stack you operate. If you consume a hosted model API, the provider owns precision, batching, kernels, and the decode path — the surviving levers are context discipline, prompt layout for the provider's prefix cache, output-length control, application-level caching, and model-tier selection. The `SKILL.md` section "If you consume a hosted API" covers that case explicitly.
