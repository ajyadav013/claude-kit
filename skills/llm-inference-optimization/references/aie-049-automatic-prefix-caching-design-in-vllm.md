---
source: https://docs.vllm.ai/en/stable/design/prefix_caching/
author: vLLM project (vLLM documentation, Developer Guide — Design Documents)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Prefix caching is only safe if the block hash covers every KV-changing input

## What it teaches
vLLM reuses KV-cache blocks across requests that share a prompt prefix, and
the whole design reduces to one question: what makes a block's contents
uniquely identifiable? The answer is a chained hash over a tuple — the parent
block's hash, the exact token IDs inside the block, and an "extra hashes"
component covering anything else that changes the tensor values (LoRA adapter
ID, multimodal input hashes, and an optional cache salt). Only full blocks are
cached. Because the hash *is* the cache key, hash quality is a correctness and
security property, not a performance knob: the docs note that pre-v0.11 keys
were not collision-free, that sha256 is now the default, and that choosing a
faster non-cryptographic algorithm raises collision risk that can produce
undefined behaviour or leak private content in multi-tenant deployments. The
rest of the design is mechanical memory management — a preallocated block
pool, an intrusive doubly-linked free queue giving O(1) reordering, LRU
eviction from the queue head, and reference counting so in-use cached blocks
are "touched" out of the free queue instead of being evicted underneath a
live request.

## Key patterns & decisions
- **Chained hash, not content hash** — each block's key folds in the parent
  block's hash, so block N is identified by its own tokens plus the entire
  prefix that produced it. Two requests can only share block N if they shared
  blocks 0..N-1, which is exactly the reuse semantics you want.
- **Exact tokens in the key, deliberately redundant** — the token tuple is
  hashed alongside the parent hash specifically to shrink collision
  probability. This is defence in depth against a hash that is otherwise
  "probably fine."
- **Extra-hash component as the extension point** — anything that changes the
  computed KV values but is not visible in the token IDs must be injected
  here. The documented examples are LoRA IDs, multimodal input hashes, and
  cache salts. Forget one and you serve another request's tensors.
- **Multimodal placeholders force explicit hashing** — an image collapses to a
  run of identical placeholder tokens after tokenization, so token IDs alone
  cannot distinguish two different images. The frontend image processor's hash
  is carried in the extra-hash field on every block the placeholders span.
- **`cache_salt` as a tenant/trust-group boundary** — an optional per-request
  salt injected into the first block's hash. Only requests presenting the same
  salt can hit each other's blocks. The stated threat is timing inference: an
  adversary probes prefixes and reads latency differences to learn what is
  cached, i.e. what someone else submitted.
- **Hash algorithm is a configurable trade-off with a security axis** —
  `--prefix-caching-hash-algo` selects sha256 (default), sha256_cbor,
  xxhash, or xxhash_cbor. The CBOR variants exist to make hashes reproducible
  across languages and versions; the pickle-based ones are not guaranteed
  stable across Python or vLLM versions. xxHash (128-bit) is faster but
  non-cryptographic.
- **Preallocated block pool plus intrusive free list** — every KVCacheBlock is
  created at manager init and the free-queue pointers live on the block
  itself. This avoids per-request Python object churn and avoids wrapping
  blocks in a separate deque, while giving O(1) moves from the middle to the
  tail.
- **Reverse-order free, LRU-from-head evict** — when a request finishes, its
  blocks go to the queue tail in reverse, so the deepest block (the one with
  the longest prefix, hence least likely to be reused) sits nearest the
  eviction end. Eviction pops the head, drops the block from the hash-to-block
  map, and clears the block hash.
- **Append-only block tables accept duplicate blocks** — v1 will not rewrite a
  request's block table to point at an equivalent cached block, so a
  greedy-decoded repeat request can cache the same content twice under
  different block IDs; the duplication is only reclaimed when the request is
  freed. Simplicity of the append-only structure was chosen over perfect
  dedup.

## When to apply / trade-offs
Prefix caching is the right default whenever many requests share a long,
stable head — a fixed system prompt, a retrieved document, a few-shot block,
a long chat history — because it removes prefill work without changing model
outputs. The costs are real but bounded: block-granular matching means a
shared prefix that ends mid-block yields no hit for that block (the worked
example shows 14 tokens overlapping 10 producing only 2 blocks / 8 tokens of
hit at block size 4), so prompt layout should put the invariant part first and
ideally align it to block boundaries. Do not treat it as free in shared
infrastructure: if untrusted tenants share one engine, either set distinct
`cache_salt` values per trust group or accept a timing side channel, and do
not downgrade to a non-cryptographic hash to buy throughput unless the
tenancy model makes collisions harmless. If you need hashes that are stable
across deployments — e.g. an external KV store or cross-version cache reuse —
pick the CBOR serialization rather than the pickle-based default.

## Fidelity check
1. Claim: the block hash is a tuple of parent hash, block tokens, and extra
   hashes covering LoRA IDs, multimodal input hashes, and cache salts.
   Support: the capture lists exactly these three components and names those
   three examples for the extra-hash field.
2. Claim: only full blocks are cached and pre-v0.11 hashing was not
   collision-free, with sha256 now the default. Support: the capture notes
   that caching applies to complete blocks only, and separately that the key
   was not guaranteed collision-free in previous versions and that sha256 is
   default as of v0.11.
3. Claim: `cache_salt` defends against timing-based inference of cached
   content. Support: the capture's cache-isolation section says the salt is
   injected into the first block's hash so only matching-salt requests can
   reuse blocks, and names timing-based attacks that infer cached content from
   latency differences.
