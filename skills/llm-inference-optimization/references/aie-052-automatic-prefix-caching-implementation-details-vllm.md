---
source: https://docs.vllm.ai/en/v0.6.2/automatic_prefix_caching/details.html
author: vLLM Team (vLLM project documentation)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Prefix reuse needs no tree — hash each KV block over its full prefix

## What it adds beyond the primary

The prefill/decode material establishes *that* the KV cache is the expensive,
memory-bound artefact of inference; this page is the missing mechanism for
reusing it across requests. Its load-bearing observation is an identity claim:
a fixed-size block of KV entries is uniquely determined by the tokens inside
the block together with all tokens preceding it, so a hash over
(prefix tokens + block tokens) is a sound content key. That collapses what
looks like a tree problem into a flat global hash table — logical blocks map
to hashes, hashes map to physical blocks, and two requests sharing a system
prompt land on the same physical block with no recomputation and no shared
tree structure to maintain. Blocks stay mutually independent and are
allocated and freed individually, so the cache can be run with familiar
operating-system cache machinery. Two extension points are worth carrying
into design work: folding a LoRA adapter ID into the hash lets one cache
serve many adapters jointly and raises the global hit rate, and swapping in
a modality-appropriate hash (the page names perceptual hashing for images)
extends reuse to multimodal inputs. The stated eviction policy is also a
usable default — evict only blocks whose reference count is zero, prefer the
least recently used among them, and break ties by evicting the block sitting
at the end of the longest prefix — which the page claims is behaviourally
identical to RadixAttention for full-attention models.

## Primary source for this cluster

[aie-049-automatic-prefix-caching-design-in-vllm.md](aie-049-automatic-prefix-caching-design-in-vllm.md) — no primary digest exists yet for the `kv-cache` cluster; the
nearest neighbour on disk is
`aie-044-prefill-and-decode-a-technical-guide-to-the-two-phases-of.md`, which
covers why the KV cache dominates decode cost but not how it is shared.

## Fidelity check

1. Claim: a KV block is uniquely identified by its own tokens plus the tokens
   in the prefix before it. Support: the capture states this as the key
   observation enabling automatic caching and illustrates it with a
   three-block sentence where block three is identified by its own tokens
   plus the preceding two blocks' tokens.
