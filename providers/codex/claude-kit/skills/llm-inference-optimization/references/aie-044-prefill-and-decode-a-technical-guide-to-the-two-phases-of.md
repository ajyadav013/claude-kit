---
source: https://www.weka.io/learn/ai-ml/prefill-and-decode/
author: WEKA (Learning Center, AI/ML)
license-note: ideas absorbed in own words; no text or code reproduced
---

# LLM inference is two workloads: compute-bound prefill, memory-bound decode

## What it teaches
A generation request is not one homogeneous unit of work. The first phase,
prefill, ingests the whole prompt (system instructions and retrieved context
included) in one parallel pass, computing attention over every token pair and
emitting the key/value cache. Its cost grows with the square of prompt length,
it saturates GPU compute, and it is what the user perceives as the wait before
anything appears. The second phase, decode, cannot be parallelised: each output
token depends on its predecessors, so the model re-reads the entire KV cache
from GPU high-bandwidth memory once per token. Decode is therefore gated by
memory transfer rate, not arithmetic, and leaves most compute idle. The article
argues that these two phases want opposite things from infrastructure, that
naive stacks run them through one shared I/O path where they contend, and that
the fixes — parallel file systems, disaggregated serving, chunked prefill — all
amount to giving each phase its own resource lane. It closes with the metric
set (TTFT, TPS, ITL, P99) and a benchmarking discipline for validating it.

## Key patterns & decisions
- **Two phases, two bottlenecks, two metrics** — prefill is compute-bound and
  measured by time-to-first-token; decode is memory-bound and measured by
  tokens-per-second. Reporting a single "latency" number for a generation
  endpoint hides which of the two is actually failing.
- **Prompt length costs quadratically, not linearly** — attention computes a
  score for every token pair, so a 1,000-token prompt implies on the order of
  1,000,000 scores and a 4,000-token prompt 16,000,000. Context bloat is a
  compute bill with a square exponent, which is the concrete argument behind
  aggressive context pruning.
- **Decode idles the GPU** — arithmetic intensity falls from roughly 200-400
  operations per byte during prefill to 60-80 during decode, and GPU
  utilisation drops to roughly 20-40%. Sizing a fleet on peak FLOPs while the
  dominant phase is memory-starved buys hardware that cannot be used.
- **Latency thresholds are perceptual, not arbitrary** — under 500ms TTFT reads
  as interactive, under 200ms reads as real-time; sustained output needs about
  50 tokens/sec per user for fluency, and below 20 tokens/sec the gaps are
  visibly wrong. These are targets an SLO can be written against.
- **Inter-token latency's tail is what breaks agents** — typical production ITL
  sits around 11-21ms, but the P99 is the number that matters. A fast median
  with a tail an order of magnitude worse survives single-turn chat and
  collapses on multi-step agentic chains, where per-step tails compound.
- **Shared I/O queues create cross-phase head-of-line blocking** — routing all
  requests through one metadata path (the article's NAS example, with 1-10ms
  added per metadata operation) lets a bandwidth-hungry prefill stall a
  latency-sensitive decode. Distributing data *and* metadata across nodes
  removes the contention rather than reordering it.
- **Disaggregated serving splits the pools** — put prefill and decode on
  separate GPU pools, each tuned and scaled for its own I/O profile. The
  DistServe work (OSDI 2024) reported serving 7.4x more requests or holding
  12.6x tighter SLO adherence versus colocating both phases; the article names
  Perplexity, Meta, LinkedIn and Mistral as production users and NVIDIA's
  Dynamo as a framework built on the idea.
- **Chunked prefill interleaves the phases instead of separating them** — split
  a long prompt into segments, cache each segment's KV pairs, and let decode
  steps run between chunks. This trades a small TTFT increase for preventing
  long prompts from monopolising the GPU; the article attributes the technique
  to the Sarathi work and cites up to 6.9x throughput improvement.
- **Benchmark with real traffic, sustained** — synthetic loads are for isolating
  a component or comparing hardware; capacity claims need captured customer
  workloads with mixed prompt lengths, genuine concurrency, and runs held for
  at least 72 hours.

## When to apply / trade-offs
This matters the moment you own the serving tier — self-hosted models, a
dedicated inference cluster, or a capacity contract you are sizing. If you call
a hosted API, the phase split is not yours to tune, but the vocabulary still
pays for itself: it tells you to instrument TTFT and inter-token latency as
separate series rather than one end-to-end timer, gives you defensible SLO
thresholds, and explains why a long system prompt hurts first-token latency
quadratically while a long *output* hurts steady-state throughput linearly. The
costs are real. Disaggregation adds a network hop to move KV cache between
pools plus two fleets to capacity-plan and fail over independently, which is
unjustifiable below meaningful concurrency. Chunked prefill deliberately makes
TTFT slightly worse to protect aggregate throughput, so it is the wrong default
for a latency-obsessed single-user demo. And the storage-architecture argument
is made by a storage vendor — the phase asymmetry and the published research
stand on their own, but treat the parallel-file-system conclusion as a vendor's
framing of a real problem rather than the only remedy.

## Fidelity check
1. Claim: prefill is compute-bound and produces the KV cache while decode is
   memory-bound and reads it per token. Support: the capture states prefill
   processes the whole prompt in parallel and generates the KV cache, and that
   decode must read the entire KV cache from HBM for every token, making data
   transfer speed rather than compute power the determinant of latency.
2. Claim: attention cost scales with the square of prompt length, 1,000 tokens
   implying ~1,000,000 scores and 4,000 tokens ~16,000,000. Support: the
   capture works exactly this example, describing N x N computations and
   contrasting 4,000,000 (wrong) with 16,000,000 (right).
3. Claim: DistServe (OSDI 2024) reported 7.4x more requests or 12.6x tighter
   SLO adherence, with production use at Perplexity, Meta, LinkedIn and Mistral
   and NVIDIA's Dynamo built around it. Support: the capture's disaggregated
   serving section and its FAQ entry both state these figures and names.
