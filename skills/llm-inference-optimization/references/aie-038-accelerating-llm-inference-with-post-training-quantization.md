---
source: https://aws.amazon.com/blogs/machine-learning/accelerating-llm-inference-with-post-training-weight-and-activation-using-awq-and-gptq-on-amazon-sagemaker-ai/
author: Pranav Murthy and Dmitry Soldatkin (Amazon Web Services)
license-note: ideas absorbed in own words; no text or code reproduced
---

# W4A16 and W8A8 relieve different bottlenecks, so PTQ is a bit-width choice

## What it teaches
Self-hosting an open-weight model is gated by GPU memory and memory bandwidth
long before it is gated by model quality, and post-training quantization (PTQ)
is the lever that moves that gate without retraining. The article frames every
choice as a two-axis notation, WxAy — how many bits the stored weights use and
how many bits the runtime activations use — and argues these two axes relieve
different bottlenecks. Compressing weights alone shrinks the bytes you must
stream from HBM per token, which is the actual limiter for small-batch
interactive serving. Compressing activations too unlocks end-to-end integer
matrix multiply, which only pays off when you are compute-bound at large batch.
It then benchmarks three models (8B dense, 70B dense, 7B vision-language) across
AWQ and GPTQ at several bit-width schemes, reporting GPU memory, end-to-end
latency, time-to-first-token, inter-token latency, and throughput at concurrency
1 through 128 — so the trade-off is measured, not asserted.

## Key patterns & decisions
- **WxAy is the vocabulary, not "quantized/unquantized"** — Wx is the weight
  bit-width, Ay the activation bit-width. W4A16 means 4-bit integer weights
  with FP16 activations; W8A8 means both are INT8. Stating a scheme is the
  only precise way to describe what was compressed and what it costs.
- **Weight-only INT8 (W8A16) is the safe default first move** — halves model
  size versus FP16 with essentially no measurable quality loss and no
  activation calibration to get wrong. The article positions it as the
  baseline many production deployments should start from.
- **Asymmetric beats symmetric at 4 bits** — a symmetric 4-bit quantizer centres
  its range on zero and wastes levels when the weight distribution is skewed or
  has one-sided outliers. Adding a zero-point offset (or per-group min/max) uses
  all 16 levels and measurably improves accuracy retention. Symmetric W4A16 is
  described as a prototyping baseline, not a shipping configuration.
- **Activations are hard to quantize because of outliers** — transformers emit
  occasional very large activation values that force a wide quantizer range,
  leaving normal values crammed into a handful of INT8 levels. SmoothQuant's
  answer is to shift the difficulty: scale outlier activation channels down and
  the matching weight channels up, a transformation that is mathematically
  equivalent but numerically friendlier.
- **AWQ: protect the ~1% of channels the activations say matter** — importance is
  read off activation statistics, not raw weight magnitude. Rather than keeping
  those channels in higher precision (which would force ragged mixed-precision
  kernels), AWQ pre-scales them and folds the inverse into the model so
  inference stays uniformly low-bit.
- **GPTQ: quantize greedily and compensate the error you just made** — it works
  layer by layer, quantizing a weight or small group and then nudging the
  still-unquantized weights to keep that layer's output close to full precision,
  guided by an approximate Hessian. One-shot, no retraining; the article cites a
  175B model compressed to 3-4 bits in under four GPU-hours.
- **Both methods need a calibration set, and both can overfit it** — a few
  hundred representative sequences are run forward to collect activation
  statistics. GPTQ in particular is noted as showing mild overfitting on
  out-of-distribution inputs, which makes calibration-set provenance a real
  design decision, not a hyperparameter you copy from a blog.
- **The measured result: 4-bit wins latency, 8-bit activations win nothing here**
  — across all three models, W4A16 variants cut GPU memory roughly 51-71% and
  roughly halved end-to-end latency, while GPTQ-W8A8 and W8A16 saved only ~35-48%
  memory and were consistently *slower* than the 4-bit variants on this
  hardware. AWQ and GPTQ at the same scheme performed near-identically.
- **Measure five metrics, not one** — GPU memory, end-to-end latency, TTFT,
  inter-token latency, and throughput. They diverge: for the 70B model, W8A8
  and W8A16 gave the *best* throughput at high concurrency while 4-bit gave the
  best latency, so a single headline number would pick the wrong scheme.

## When to apply / trade-offs
This applies only when you are self-hosting open-weight models on GPUs you pay
for; it is irrelevant to teams consuming a hosted model API, where the provider
owns the serving stack and you tune model tier and caching instead. Within
self-hosting, PTQ is attractive precisely because it skips retraining — the cost
is a calibration pass, a quality-regression risk that you must measure on your
own eval set, and a permanent second artifact to version and track alongside the
base weights. Do not treat the article's latency numbers as portable: it says
plainly that the configurations were not tuned for peak performance and exist to
show relative ordering, and the W8A8-is-slower result is a property of that
hardware and serving stack. Skip quantization entirely when the model already
fits comfortably with headroom, when the domain is accuracy-critical and you
lack an eval harness sensitive enough to catch a small degradation, or when your
bottleneck is upstream (retrieval, tool calls, network) rather than the GPU.

## Fidelity check
1. Claim: 4-bit schemes cut GPU memory roughly 51-71% while 8-bit-activation
   schemes saved only ~35-48%. Support: the capture's memory table shows
   Llama-3.3-70B dropping from 142.9 GB raw to 41.4-41.7 GB (70.82-71.03%) under
   W4A16 variants versus 74.7 GB (47.76%) under W8A8/W8A16, and Qwen2.5-VL-7B
   dropping 50.94-51.26% versus 34.98%.
2. Claim: GPTQ-W8A8 and W8A16 were slower end-to-end than the 4-bit variants on
   the 8B model. Support: the capture's latency table lists Llama-3.1-8B at C=1
   as 3.33-3.53 s for the four W4A16 variants but 5.47 s (W8A8) and 5.03 s
   (W8A16), with the same ordering holding out to C=128.
3. Claim: 8-bit schemes gave the best throughput at high concurrency for the 70B
   model even though 4-bit gave the best latency. Support: the capture's
   throughput table shows Llama-3.3-70B at C=128 reaching 12.85 (W8A8) and 13.08
   (W8A16) tokens/s versus 11.5-11.77 for the W4A16 variants.
