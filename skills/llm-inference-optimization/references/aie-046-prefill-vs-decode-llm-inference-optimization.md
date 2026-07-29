---
source: https://outcomeschool.com/blog/prefill-vs-decode-llm-inference-optimization
author: Amit Shekhar (Outcome School)
license-note: ideas absorbed in own words; no text or code reproduced
---

# End-to-end latency is TTFT plus (N-1) times TPOT

## What it adds beyond the primary
Where the primary establishes the phase asymmetry and its metrics, this piece
supplies the arithmetic that ties them together — total latency is TTFT plus
one TPOT for each output token after the first, worked through as roughly 5.4
seconds for a 400ms TTFT and a 200-token answer streaming at 25ms per token —
plus the conversion that makes TPOT legible as a product decision (25ms is 40
tokens per second, 50ms is 20). It names batch size as the explicit knob behind
the per-user-latency versus system-throughput tension, so an interactive
assistant and an offline summarisation job are tuned in opposite directions.
It covers two techniques the primary omits: continuous batching, which re-makes
the admission decision every decode step so a slot freed by a finished request
is refilled immediately rather than idling until the slowest member of a static
batch completes; and PagedAttention, which stores the KV cache in small
fixed-size blocks (about 16 tokens) addressed through a block table instead of
one contiguous per-request reservation sized for the worst-case answer. Its
sharpest contribution is separating two ideas that are routinely conflated —
PagedAttention is the memory layout that eliminates reservation waste, while
prefix caching is the reuse of already-computed KV across requests that share
a leading span; the former is what makes the latter's block sharing physically
possible, and prefix caching degrades to a full prefill when no prefix is
actually shared. It also flags the capacity trap behind all of this: the KV
cache is per-user and grows one entry per generated token, so long contexts at
high concurrency can push it past the size of the model weights themselves.

## Primary source for this cluster
`aie-044-prefill-and-decode-a-technical-guide-to-the-two-phases-of.md`

## Fidelity check
1. Claim: end-to-end latency equals TTFT plus (N-1) multiplied by TPOT, worked
   as ~5.4 seconds from a 400ms TTFT, 200 output tokens, and 25ms TPOT.
   Support: the capture states this formula, explains the minus-one as the
   first token already being counted inside TTFT, and runs exactly this
   numeric example to about 5.4 seconds.
