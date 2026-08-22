---
source: https://www.digitalocean.com/community/tutorials/llm-inference-optimization-stack-part-1
author: Shaoni Mukherjee (DigitalOcean Community)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Only structured pruning speeds up a dense GPU; unstructured just shrinks files

## What it adds beyond the primary

The primary for this cluster splits a request into prefill and decode and
argues those two phases are different workloads. This piece sits one layer
below that, at the *model* level rather than the *phase* level, and its
distinct contribution is **pruning** — a topic absent from the rest of this
cluster and from claude-kit entirely. The load-bearing claim is that pruning
splits into two kinds with opposite operational consequences: unstructured
pruning zeroes scattered individual weights, keeps matrix shapes intact, gets
good quality-per-byte, and buys you **no GPU speedup**, because dense tensor
cores still multiply through the zeros; structured pruning removes whole
attention heads, neurons, or layers, changes the shape, and therefore yields
real throughput. The exception is NVIDIA's 2:4 sparsity on Ampere and later,
where exactly two of every four consecutive weights must be zero — a pattern
regular enough for hardware to skip, quoted at close to 2x on sparse ops, and
worth nothing if your sparsity does not satisfy the constraint exactly. CPU
inference inverts this: llama.cpp-style CPU serving is memory-bandwidth bound,
so skipping zero weights genuinely helps because less data must be loaded.
The article also frames the whole five-technique set as a stack with distinct
jobs — quantization and pruning shrink the model, distillation replaces it,
KV caching manages memory, speculative decoding attacks sequential generation —
which is the framing our cluster needs to keep the techniques from being
treated as interchangeable "make it faster" knobs.

Secondary additions on the quantization side mostly corroborate the AWQ/GPTQ
digests, but two specifics are useful: the four-way ladder PTQ → dynamic →
static → QAT ordered by cost and by accuracy retention (dynamic quantizes
activations at runtime and suits CPU; static needs a calibration dataset and
gives lower latency; QAT simulates quantization during training and is the
fallback when INT4 degradation is unacceptable), and the observation that
production systems increasingly run **mixed precision** — sensitive layers kept
high, tolerant layers compressed hard — rather than one bit-width everywhere.

Named pruning methods worth carrying forward: magnitude pruning (cheap,
iterative prune-then-finetune beats one-shot, but magnitude is a proxy for
importance, not importance itself); Wanda, which scores a weight by magnitude
times the norm of its input activation, so a small weight feeding a hot neuron
survives, runs in minutes with no gradients and no retraining; SparseGPT, which
reuses GPTQ's second-order Hessian machinery to correct surviving weights after
each removal, and can do pruning and quantization in one pass; and ShortGPT's
Block Influence, which drops whole layers whose output barely differs from
their input — redundancy concentrated in the middle of the network, not at the
ends. Early exit is mentioned as the inference-time version of layer dropping:
stop at an intermediate layer when confidence is already high, so easy inputs
pay less latency than hard ones.

For a claude-kit rule, the reusable shape is: **compression is a
capability-risk decision, not a cost decision.** The article is explicit that
over-aggressive compression increases hallucination, degrades reasoning, and
destabilises output, and that INT8 is near-invisible while 4-bit shows up first
on complex reasoning — which means the eval suite, not the memory graph, is the
gate on how far you compress.

## Primary source for this cluster

[aie-044-prefill-and-decode-a-technical-guide-to-the-two-phases-of.md](aie-044-prefill-and-decode-a-technical-guide-to-the-two-phases-of.md)

## Fidelity check

1. Claim: unstructured pruning gives smaller files but not faster GPU
   inference; structured pruning gives real throughput. Support: the capture
   states modern GPUs are optimised for dense matmul and do not speed up just
   because half the values are zero, that without specialised sparse kernels
   unstructured pruning yields smaller model files but not faster inference,
   and that structured pruning makes the model smaller in shape so dense
   matmul and standard hardware still apply and you get real throughput gains.
