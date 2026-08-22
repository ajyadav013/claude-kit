---
source: https://pub.towardsai.net/llm-inference-optimization-prefill-vs-decode-6e003d48b2ca
author: Robi Kumar Tomar (Towards AI)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Measure prefill and decode separately; flat GPU memory is KV pre-reservation

## What it adds beyond the primary

The primary establishes *why* prefill and decode differ; this piece is the
operator's runbook for proving it on a live server. Three things are genuinely
new here. First, concrete instrumentation: vLLM exposes per-phase timing
histograms, and the article gives the PromQL shape for turning them into an
average prefill and an average decode time per request over a window, with the
discipline that makes the numbers trustworthy — restart the server so counters
reset, issue one request with a fixed prompt and fixed token budget, no
concurrent traffic. Second, a debugging trap the primary never mentions: GPU
memory that plateaus immediately after startup is usually the framework's
pre-allocated KV pool, not a full cache or an idle GPU, and `nvidia-smi` cannot
show KV growth *inside* that reservation — the framework's own startup log is
the source of truth. Teams that misread this add GPUs or disable features to
chase a bottleneck that is not there. Third, the multi-GPU angle: under tensor
parallelism, prefill amortises its NCCL collectives across one or a few passes
while decode re-fires them on every generated token, so adding GPUs to solve a
memory problem can manufacture a communication-bound decode problem. The
article also supplies a tool ladder (Prometheus/Grafana for trends, nvidia-smi
for sanity checks, `NCCL_DEBUG=INFO` to confirm per-token collectives, Nsight
Systems for idle gaps in the timeline, Nsight Compute only once you know which
kernel is slow) and a nuance on `--gpu-memory-utilization`: lowering it looks
like it frees memory but can silently cap batch size or force paging, hurting
decode more than the memory it returned was worth.

## Primary source for this cluster

[aie-044-prefill-and-decode-a-technical-guide-to-the-two-phases-of.md](aie-044-prefill-and-decode-a-technical-guide-to-the-two-phases-of.md)

## Fidelity check

1. Claim: vLLM exposes separate prefill and decode timing histograms and the
   article computes per-request averages from their sum and count over a
   5-minute window. Support: the capture's PromQL section shows both queries
   built from `increase(...sum[5m])` divided by `increase(...count[5m])` against
   `vllm:request_prefill_time_seconds` and `vllm:request_decode_time_seconds`.
