---
source: https://discuss.vllm.ai/t/understanding-vllm-kv-cache/2061
author: vLLM Forums (discuss.vllm.ai) — thread by rahulraman1604, answers from the RunLLM assistant bot
license-note: ideas absorbed in own words; no text or code reproduced
---

# vLLM's KV cache: four structures driven by three scheduler calls

## What it adds beyond the primary

Mostly corroborates the primary design doc, but adds two things the design
page does not give you. First, it names the concrete call sequence the
scheduler walks per request — look up already-computed blocks, allocate
slots for the uncached remainder, then free on completion — which is the
minimum interface any reimplementation has to expose. Second, it resolves a
real terminology collision across vLLM's own docs: the prefix-caching page
says "block pool" and the hybrid KV cache manager page says "memory pool",
and the thread's answer is that these denote the same resource layer, with
"block pool" naming the software structure that tracks allocation and
"memory pool" naming the reserved GPU memory underneath. It also separates
two concerns that are easy to conflate — block *assignment* is the cache
manager's job, while the actual write of KV tensors into those blocks
happens inside the model runner during the forward pass.

Provenance caveat worth carrying: the substantive answers here come from an
automated assistant (RunLLM) and are hedged in places, so treat the
function names as pointers into the source tree rather than as a verified
API contract.

## Primary source for this cluster

[aie-049-automatic-prefix-caching-design-in-vllm.md](aie-049-automatic-prefix-caching-design-in-vllm.md)

## Fidelity check

1. Claim: the scheduler's per-request sequence is get_computed_blocks, then
   allocate_slots, then free. Support: the capture's step-by-step answer
   lists get_computed_blocks(request), allocate_slots(request, num_tokens,
   computed_blocks), and free(request) with those roles.
