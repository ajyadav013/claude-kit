---
source: https://theorempath.com/topics/speculative-decoding-and-quantization
author: Robby Sneiderman (TheoremPath)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Speculative decoding is provably lossless; quantization needs an eval gate

## What it adds beyond the primary

No other capture in this cluster exists yet, so this is the cluster's whole
evidence base, and it supplies the one distinction that governs how an
LLM-serving change should be reviewed: the two headline inference
optimizations differ in kind, not just in degree. Speculative decoding's
accept/resample rule makes its output distribution identical to the target
model's, so a draft model only ever changes throughput; quantization, by
contrast, injects a bounded numerical error whose downstream damage is
task-dependent and shows up first in confidence calibration, rare-token
generation, and long-context behavior rather than in aggregate perplexity.
It also gives the arithmetic needed to size the trade-off up front —
expected accepted tokens per verification step, per-weight quantization
error scaling, and group-scale memory overhead — plus a default recipe
(quantized target, full-precision draft) and the reason the reverse hurts.

## Primary source for this cluster

[aie-041-improving-the-economics-of-llm-inference-with-speculative.md](aie-041-improving-the-economics-of-llm-inference-with-speculative.md) — no primary digest exists for the `speculative-decoding`
cluster yet; this stub is currently its only capture.

## Fidelity check

1. Claim: speculative decoding preserves the target distribution exactly.
   Support: the capture states a theorem that the algorithm with modified
   rejection sampling produces tokens distributed exactly per the target
   model p regardless of draft quality, and repeats in a "watch out" note
   that it is not an approximation.
