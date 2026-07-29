---
source: https://arxiv.org/html/2607.02525v1
author: Bing Xie, Zhipeng Wang, Masahiro Tanaka, Zheng Zhen (arXiv preprint 2607.02525v1)
license-note: ideas absorbed in own words; no text or code reproduced
---

# The pending request queue, not the cache, predicts which KV blocks to keep

## What it teaches
Production LLM serving engines already know how to *share* KV cache blocks
across requests: vLLM hashes blocks by content and prefix position, SGLang
organises them in a radix tree for longest-prefix matching. What neither does
is look at the requests still waiting in line and ask which of them share
prefixes with each other. That queue is itself a structured workload, and its
shape is a prediction of the cache demand about to arrive. PEEK builds an
incremental radix tree over the pending queue, uses it to rank admission so
that a "pioneer" request warms a prefix its siblings then reuse, and feeds the
same tree into the eviction hook so blocks that queued work depends on are
freed last. Because scheduling and eviction read one signal, they stop fighting
each other. The paper's core failure mode is scheduling-induced thrashing: with
interleaved tenants and a cache too small to hold two prompts, arrival-order
admission prefills, evicts, and refills the same prefixes for a 0% hit rate,
while cluster-ordered admission on the identical requests reaches 62.5%.

## Key patterns & decisions
- **Model the queue, not just the cache** — the reusable asset is not what is
  cached now but what the pending work will demand next. An incremental
  compressed trie over waiting prompts, maintained O(D) per insert and remove
  with no per-cycle rebuild, exposes sharing clusters the engine cannot see.
- **Co-design admission and eviction on one signal** — the paper's framing is
  that existing engines have three gaps: visibility (schedulers ignore
  inter-queue sharing), coupling (scheduling and eviction are separate), and
  co-design (both could use the same demand signal but none does). Sharing one
  data structure removes the need for explicit coordination between them.
- **Admission ordering is the dominant lever; eviction only refines it** — the
  cluster-aware sort alone lands within 3 percentage points of the full stack
  on cache hit. The queue-aware eviction hook adds 0–3% on SGLang and is flat
  on vLLM, and on an unmodified scheduler it is flat outright. The authors'
  conclusion is blunt: eviction cannot manufacture temporal locality that the
  scheduler never created.
- **LRU is the wrong default when the future is knowable** — LRU was designed
  for OS page caches with unknown future access. A serving queue encodes
  upcoming work, so LRU can evict exactly the prefix the next admitted batch
  needs. PEEK scores each candidate block by the depth-weighted pending demand
  along its ancestor chain and evicts the zero-demand blocks first.
- **Locality optimisations starve the unshared minority — budget for that
  explicitly** — grouping cluster members contiguously buys almost no extra
  cache hit (−0.1 to +1.4 pp on SGLang, −3.0 to −0.4 pp on vLLM) but costs
  10–29% on TTFT and end-to-end latency by deferring singleton requests. A
  fairness lane interleaved by stride, with the share widening as singletons
  accumulate or the oldest singleton's wait approaches its SLO, recovers
  2.4–15.1%. The fairness share is clamped so locality still dominates.
- **Guard the optimisation so it costs nothing when it cannot pay** — a cheap
  primitive scans the trie's root children and short-circuits the whole
  machinery when no prefix sharing exists. On workloads with no exploitable
  structure the system tracks the naive baseline within about 1.5%.
- **Prove no-regress on the workloads you do not help** — two of five workloads
  exist purely to show the optimisation does no harm: already prefix-coherent
  agentic bursts, and singleton-dominated chat. Reported deltas are within ±2%
  on end-to-end and throughput, with wider ±5–7% envelopes on TTFT.
- **Adapt the mechanism to the host's data structure** — against SGLang's radix
  cache a tree-versus-tree co-descent collapses N per-request lookups into C
  per-cluster ones. Against vLLM's flat block-hash cache no co-descent is
  possible, so it falls back to per-request probes and reads only the cluster
  signals from its own trie. The idea survives; the implementation bends.
- **Integrate by adapter, not by fork** — a small native core plus roughly 800
  lines of Python per engine that patch the scheduler and block pool, toggled
  by environment flags, with no upstream fork to maintain.

## When to apply / trade-offs
This is intra-replica serving-infrastructure knowledge, relevant when you
operate your own inference engine under real KV-cache pressure with workloads
that have exploitable prefix structure — shared system prompts across tenants,
long-document RAG, multi-turn agentic pipelines. It is irrelevant if you call a
hosted API, and it is orthogonal to within-sequence KV compression, to
prefill/decode disaggregation, and to cross-replica routing, all of which
compose beneath or above it. The costs are real: decode-side per-token time
rose 8–26% in the chat workload as prefill recovery pushed larger decode
batches through, and the fairness controller exists only because the locality
optimisation actively harms unshared requests. Do not reach for this when your
traffic is already prefix-coherent by arrival order or is genuinely singleton
heavy — the paper's own measurements show the ceiling there is noise. The
transferable lesson for any caching system is broader than LLM serving: if you
have a queue of pending work, its structure is a free prediction of future
demand, and admission order usually matters more than eviction policy.

## Fidelity check
1. Claim: admission ordering dominates and eviction cannot create locality the
   scheduler did not establish. Support: the capture states the cluster-aware
   sort alone lands within 3 pp of the full stack on cache hit, that the
   eviction hook adds 0–3% on one engine and is flat on the other, and states
   directly that eviction cannot create temporal locality the scheduler did not
   first establish.
2. Claim: contiguous cluster grouping buys little cache hit but inflates
   latency, and a dynamic fairness lane recovers part of it. Support: the
   capture reports the group-major cache-hit deltas of −0.1 to +1.4 pp and
   −0.4 to −3.0 pp, a 10–29% TTFT/E2E cost from singleton deferral, and a
   2.4–15.1% recovery from the dynamic-lane controller.
3. Claim: the thrashing example goes from 0% to 62.5% cache hit purely by
   reordering. Support: the capture works through eight interleaved requests
   across three tenants on a cache holding one prompt, showing arrival-order
   admission at 0% hit and cluster-reordered admission at 62.5%.
