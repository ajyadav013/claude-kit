---
source: https://vrlatech.com/llm-quantization-explained-int4-int8-fp8-awq-and-gptq-in-2026/
author: VRLA Tech
license-note: ideas absorbed in own words; no text or code reproduced
---

# Weight precision is a deployment-time capacity knob with a reasoning tax

## What it teaches
Self-hosted model serving has a sizing arithmetic that is entirely mechanical:
bytes-per-parameter times parameter count gives the weight footprint, so a 70B
model needs roughly 140GB at BF16 (2 bytes), 70GB at FP8 or INT8 (1 byte), and
36-40GB at INT4 (0.5 bytes), plus a further 15-25% for KV cache and framework
overhead at typical batch sizes. Quantization is the lever that moves a model
across a hardware boundary — the same 70B that cannot fit a single 96GB card at
BF16 fits comfortably at INT4. The article separates two things that are often
conflated: the *format* (FP32, BF16, FP8, INT8, INT4, NF4) which fixes the
storage width, and the *method* (AWQ, GPTQ, GGUF, bitsandbytes) which decides
how the rounding error is distributed across weights. It then attaches rough
quality-retention figures to each combination and argues the choice is driven
by which GPU generation you have and whether you are serving many users or one.

## Key patterns & decisions
- **Size the deployment from bytes-per-parameter, not vibes** — BF16 is 2 bytes,
  FP8/INT8 1 byte, INT4 0.5 bytes per parameter. Multiply by parameter count,
  then add 15-25% headroom for KV cache and runtime overhead. This single
  calculation decides whether a model fits one card, needs NVLink, or is
  infeasible, before you touch any serving config.
- **FP8 is the 2026 default when the silicon supports it** — Hopper and
  Blackwell tensor cores execute FP8 natively, so it is memory-cheap *and*
  compute-fast rather than a pure memory trade. Reported quality is ~99% of
  BF16, which makes it the least-regret choice for production inference on
  current hardware.
- **INT8 is the portability fallback, not the quality choice** — same 1 byte
  per parameter as FP8 but slightly worse quality (~97-98%) because integer
  quantization is a coarser fit to the weight distribution. Its argument is
  hardware support: it works on older GPUs that lack FP8 tensor cores.
- **AWQ protects the weights that matter** — activation-aware weight
  quantization runs a calibration pass, identifies the weights whose
  perturbation most damages output quality, and shields those from aggressive
  rounding while compressing the rest harder. That non-uniform allocation is
  why AWQ INT4 (~94-96%) beats naive uniform INT4.
- **GPTQ trades a little quality for ecosystem reach** — it minimises
  per-layer quantization error using second-order weight information, landing
  slightly below AWQ (~93-95%) in most benchmarks, but there are far more
  pre-quantized GPTQ checkpoints and broader tooling support across vLLM,
  Hugging Face Transformers, and text-generation-webui.
- **GGUF is a workstation format, not a serving format** — the llama.cpp/Ollama
  format's distinguishing feature is CPU+GPU hybrid execution: layers spill
  into system RAM when VRAM runs out. That offloading is exactly what caps
  throughput, so it suits single-user local development and edge boxes and is
  the wrong answer for multi-tenant production serving.
- **Quantization level inside GGUF is its own decision** — Q5_K_M and Q6_K sit
  near BF16 quality (~95-97%), Q4_K_M is the common default (~92-94%), and Q2_K
  degrades visibly (~80-85%). "Running GGUF" is underspecified without the
  level.
- **Quantized weights are not fine-tunable in place** — QLoRA does not train
  the quantized weights; it freezes a base in NF4 (a 4-bit type shaped for
  normally-distributed weights) and trains BF16 LoRA adapters around it.
  Training the quantized weights directly degrades quality further.
- **Task type modulates the acceptable floor** — INT4 loss is tolerable for
  summarisation, classification, and code completion, and most visible on
  multi-step reasoning and math. The same 94% aggregate number is a different
  risk depending on what the endpoint is for.

## When to apply / trade-offs
This matters only when you own the inference — self-hosted open-weight models on
your own GPUs or a rented instance — and is irrelevant when you call a hosted
API, where precision is the provider's concern. Reach for it when the model you
want does not fit the card you have, or when you want more throughput from
hardware you already run. The cost is a quality regression you must measure
rather than assume: the retention percentages here are aggregate benchmark
figures from a hardware vendor's guide, and your own eval set is the only
authority on whether a 4-6% aggregate drop is invisible or fatal for your
workload. Do not quantize reflexively — if the model already fits at BF16 or
FP8 with headroom, the compression buys nothing and only adds a variable to
debug. Treat these numbers as sizing heuristics for capacity planning, not as
guarantees; note also that the source is a system builder whose recommendations
align with the hardware it sells, so the format rankings are more trustworthy
than the specific GPU recommendations.

## Fidelity check
1. Claim: a 70B model needs ~140GB at BF16 and 36-40GB at INT4, with 15-25%
   added for KV cache and overhead. Support: the capture states 2 bytes per
   parameter for BF16 giving 140GB for 70B, lists 36-40GB in the INT4 column of
   its VRAM table, and appends a note to add 15-25% for KV cache and framework
   overhead at typical batch sizes.
2. Claim: AWQ preserves quality by identifying high-impact weights during
   calibration and quantizing the rest more aggressively. Support: the capture
   describes AWQ as analysing activation patterns during calibration to find the
   weights with the highest impact on output quality, protecting them, and
   compressing less important weights harder.
3. Claim: GGUF is unsuitable for production multi-user serving because CPU
   offloading limits throughput. Support: the capture explicitly advises against
   GGUF for production high-throughput serving, describes it as designed for
   developer workstations and edge deployments, and its FAQ says vLLM with AWQ
   or FP8 delivers substantially higher throughput because GGUF's CPU offloading
   is a throughput-limiting trade.
