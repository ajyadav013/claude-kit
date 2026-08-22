---
source: https://redis.io/blog/prefill-vs-decode/
author: Jim Allen Wallace (Redis)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Prefill is compute-bound, decode is memory-bandwidth-bound — two bugs, not one

## What it teaches
An LLM request is not one operation, it is two with opposite hardware
profiles. Prefill ingests the whole prompt in a single parallel pass and
builds the key-value cache; because attention makes every token attend to
every other token, its work grows superlinearly with prompt length, and it
saturates GPU math units — it is compute-bound. Decode then emits one token
at a time, each conditioned on all prior tokens, so every step must re-read a
KV cache that keeps growing; it cannot exploit parallel hardware and is
limited by memory bandwidth. The user-visible metrics split the same way:
prefill dominates time to first token (TTFT), decode dominates inter-token
latency (ITL) and therefore total wall time for long outputs. The practical
consequence is diagnostic discipline — measure the input/output length
distribution and both TTFT and ITL before choosing an optimization, because
prefill fixes (efficient attention kernels, semantic caching) and decode
fixes (quantization, speculative decoding, bigger batches) belong to
disjoint families, and the two phases actively contend for the same GPU.

## Key patterns & decisions
- **Split the latency metric before splitting the fix** — end-to-end latency
  hides which phase is slow. TTFT proxies prefill (plus queueing and
  network); ITL is derived as (end-to-end latency minus TTFT) divided by
  (output tokens minus one). Instrument both or you will tune blind.
- **Attention makes prompt length quadratic-ish, not linear** — the article
  cites a Llama 3.1 70B benchmark where 32,768 input tokens gave 472 ms TTFT
  while 122,880 input tokens gave roughly 2.2 s. TTFT grew faster than the
  prompt, and the gap widens with context. Budget context length as a latency
  cost, not just a token cost.
- **The KV cache is the decode bottleneck, and it grows per token** — it
  starts at prompt size and adds an entry per generated token; across many
  concurrent long-response requests it can exceed the model's own size
  several times over. Every decode step reads all of it.
- **Output length, not input length, usually owns total latency** — the
  worked figure: a 500-token response at 80 ms ITL spends about 40 s in
  decode, next to which a 200 ms TTFT is noise. Long-output workloads should
  not be optimized for TTFT.
- **Map workload shape to the phase that will hurt** — RAG (thousands of
  retrieved context tokens, short answers) is prefill-heavy and TTFT-bound.
  Code generation and long-form writing are decode-heavy and ITL-bound.
  Interactive chat needs both, with tail latency mattering most. Batch jobs
  care about throughput and cost per token, not latency at all.
- **The two phases contend, so scheduling is a real design decision** —
  incoming prefills can block in-flight decode streams and make already-
  streaming responses stutter; long prefills also inflate TTFT for queued
  requests. The article notes an early inference-framework policy that
  prioritized prefill to improve TTFT and consequently starved decode.
- **Semantic caching and prefix caching are complements, not substitutes** —
  prompt-prefix reuse only shrinks repeated prompt-processing work, whereas
  semantic caching sits above the inference stack and can skip the model
  entirely on a hit, erasing both prefill and decode cost. Mechanically it is
  vector search: embed the incoming query, compare against cached query
  vectors, serve when similarity clears a configured threshold.
- **Decode levers all reduce bytes moved per step** — quantization is the
  blunt one (cited: INT4 KV-cache quantization gave a 57% decode latency
  reduction on LLaMA3-8B; W8A8 gave 20–30% on prefill and 40–60% on decode;
  W4A16 was more variable). Speculative decoding is the structural one: a
  small draft model proposes tokens the main model verifies in parallel, with
  a cited 3.55x speedup on Llama 3.3 70B — but the draft model's own latency
  becomes the new floor, so it must be fast before it is accurate.
- **Efficient attention is the free prefill win** — FlashAttention-class
  kernels reorder long-prompt processing for speed with identical output, and
  ship on by default in many modern serving frameworks, so check whether you
  already have it before engineering anything else.

## When to apply / trade-offs
This matters the moment you own the serving path or the latency SLO for an
LLM feature — self-hosted inference, a gateway in front of a provider, or any
product where "it feels slow" is a bug report you must triage. The
diagnostic split (length distribution, then TTFT, then ITL) is cheap and
should precede any optimization spend. The cost is instrumentation and the
discipline not to apply a fashionable fix to the wrong phase: quantization
will not rescue a RAG app whose pain is a 2-second prefill on 100K tokens of
retrieved context, and semantic caching will not smooth a code-generation
stream. Quantization additionally trades numeric fidelity for speed, so it
needs an eval gate before it ships. Semantic caching trades correctness risk
for latency — a too-loose similarity threshold serves the wrong cached answer
— and is inappropriate where every response must be freshly grounded or
personalized. If you consume a hosted API and cannot touch batching, kernels,
or precision, only the app-layer levers (prompt/context size discipline,
caching, output-length control) are actually available to you, and the rest
of this is background for choosing a vendor or a model tier. Note also that
the source is vendor content: the phase model and metric definitions are
general, but the semantic-caching section is positioning for a Redis product.

## Fidelity check
1. Claim: prefill is compute-bound and decode is memory-bandwidth-bound.
   Support: the capture states prefill is usually compute-bound (limited by
   how fast the GPU does math) and decode usually memory-bandwidth-bound
   (limited by how fast the GPU moves data), and says this difference shapes
   request scheduling and hardware allocation.
2. Claim: TTFT scaled superlinearly with prompt length in a cited benchmark.
   Support: the capture gives a Llama 3.1 70B benchmark with 472 ms TTFT at
   32,768 input tokens and about 2.2 seconds at 122,880, and states TTFT grew
   faster than the prompt itself.
3. Claim: the quantization and speculative-decoding numbers. Support: the
   capture reports 57% decode latency reduction from 4-bit (INT4) KV cache
   quantization on LLaMA3-8B, 20–30% prefill / 40–60% decode gains for W8A8,
   variable results for W4A16, and a 3.55x speculative-decoding speedup on
   Llama 3.3 70B, adding that the draft model's latency becomes the new
   bottleneck.
