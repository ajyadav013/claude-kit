---
name: llm-inference-optimization
description: Self-hosted LLM serving performance — quantization (AWQ/GPTQ/FP8/INT4), speculative decoding, prefill vs decode, KV cache and prefix caching. Use when sizing GPUs, cutting inference cost, or diagnosing TTFT versus inter-token latency.
---

# LLM Inference Optimization

Make one model serve more traffic, faster, on less hardware. Quantization, pruning, speculative decoding, batching, and KV-cache reuse are not five ways of saying "make it faster" — each one buys a different resource back, and each one bills a different account (memory, accuracy, tail latency, operational surface). The single question that orders all of them is whether the workload is **prefill-bound** or **decode-bound**, because those two phases have opposite hardware profiles and disjoint fixes. This skill covers the self-hosted case, where you own the serving stack; the closing section says which levers survive when you consume a hosted API instead.

## When to use

- Sizing GPUs for a self-hosted open-weight model, or deciding whether a model fits the card you already have
- Choosing a precision format (BF16 / FP8 / INT8 / INT4) or a quantization method (AWQ, GPTQ, GGUF) before a deploy
- Triaging "the model feels slow" into a specific phase — is time-to-first-token bad, or is the token stream stuttering?
- Deciding whether speculative decoding will help or hurt a particular traffic mix
- Diagnosing why concurrency collapses at long context lengths, or why a KV cache exceeds the model weights
- Designing prompt layout so prefix caching actually hits, and setting cache-key isolation for multi-tenant serving
- Debugging a serving instance whose GPU memory plateaus at startup and never moves
- Deciding between chunked prefill, disaggregated prefill/decode pools, and simply buying more GPU
- Writing latency SLOs for a generation endpoint that separate TTFT from inter-token latency
- Reviewing a proposed inference-cost reduction that stacks several techniques in one change
- Evaluating whether a claimed speedup from a vendor benchmark transfers to your hardware and traffic shape

Scope boundary — this skill owns **serving-side inference economics for models you host**. Adjacent territory belongs elsewhere: application-level response caching and cache invalidation belong to `redis-caching-patterns`; general service profiling and hot-path work belong to `performance-optimization`; generating the concurrency to measure any of this belongs to `load-testing`; per-call token/latency/cost telemetry belongs to `langfuse-llm-tracing`; RED metrics, dashboards, and alerting belong to `observability-and-logging`.

## Core conventions

### The phase split is the first thing to understand

A generation request is two workloads glued together, not one.

**Prefill** ingests the entire prompt — system instructions, retrieved context, chat history, the user's turn — in a single parallel pass, and emits the key/value cache. Attention scores every token pair, so its cost grows with roughly the square of prompt length rather than linearly: doubling a prompt quadruples the score matrix. Prefill saturates the GPU's arithmetic units. It is **compute-bound**, and it is what the user experiences as the wait before anything appears.

**Decode** emits one token at a time, each conditioned on all its predecessors, so it cannot be parallelised within a sequence. Every step re-reads the whole (and growing) KV cache out of high-bandwidth memory to produce one token. It is **memory-bandwidth-bound**, and it leaves most of the GPU's compute idle — one guide puts arithmetic intensity at roughly 200–400 operations per byte during prefill versus 60–80 during decode, with GPU utilisation falling to roughly 20–40%.

Practical consequence: a fleet sized on peak FLOPs is sized for the phase that isn't the bottleneck. And any optimization aimed at the wrong phase is wasted spend — quantizing weights will not rescue a RAG endpoint whose pain is a two-second prefill over 100K tokens of retrieved context.

### Split the metric before you split the fix

- **TTFT (time to first token)** proxies prefill, plus queueing and network.
- **ITL / TPOT (inter-token latency, time per output token)** proxies decode. Derive it as `(end_to_end − TTFT) / (output_tokens − 1)`.
- **End-to-end latency** is `TTFT + (N − 1) × TPOT`. Worked: a 400 ms TTFT with 200 output tokens at 25 ms each is about 5.4 seconds — the TTFT is 7% of the wall clock. For long outputs, decode owns total latency and TTFT is noise.
- **Throughput** (tokens/sec aggregate, requests/sec) is the batch-level number and moves in the opposite direction from per-user latency.

Report the tail, not the median. Typical production ITL sits in the low tens of milliseconds; a P99 an order of magnitude worse survives single-turn chat and destroys multi-step agentic chains, where per-step tails compound.

Rough perceptual thresholds worth writing SLOs against: TTFT under ~500 ms reads as interactive and under ~200 ms as real-time; sustained output around 50 tokens/sec per user reads as fluent, and below ~20 tokens/sec the gaps are visible. Treat these as starting targets, not physics.

### Match the workload shape to the phase that will hurt

| Workload | Shape | Bound by | Optimize |
|----------|-------|----------|----------|
| RAG / document QA | Thousands of context tokens, short answer | Prefill, TTFT | Prefix caching, efficient attention kernels, context pruning, chunked prefill |
| Code generation, long-form writing | Modest prompt, long output | Decode, ITL | Quantization, speculative decoding, larger batches |
| Interactive chat | Both, tail-sensitive | Both | Continuous batching, prefix caching on history, tail-latency work |
| Offline batch (summarise a corpus) | Anything, no user waiting | Throughput / cost per token | Large batches, aggressive quantization, high GPU utilisation |

Measure your own input/output length distribution first. The distribution, not the model card, decides which column you are in.

### Size the deployment from bytes per parameter

The weight footprint is mechanical: bytes-per-parameter × parameter count. BF16 is 2 bytes, FP8 and INT8 are 1 byte, INT4 is 0.5 bytes. A 70B model is therefore roughly 140 GB at BF16, ~70 GB at 8-bit, and ~36–40 GB at INT4 — then add roughly 15–25% for KV cache and framework overhead at typical batch sizes. That one calculation decides whether the model fits one card, needs multi-GPU interconnect, or is infeasible, before you touch a serving config.

Do this arithmetic *before* evaluating techniques. Quantization's headline value is often crossing a hardware boundary — the same 70B that cannot fit a single large card at BF16 fits comfortably at INT4 — not shaving milliseconds.

### Quantization is a two-axis choice, notated WxAy

"Quantized" is not a specification. **Wx** is the weight bit-width, **Ay** the activation bit-width. W4A16 is 4-bit weights with 16-bit activations; W8A8 is 8-bit both. The axes relieve different bottlenecks:

- **Weight-only compression (W4A16, W8A16)** shrinks the bytes streamed from HBM per token. That is the actual limiter for small-batch interactive serving — the decode phase.
- **Compressing activations too (W8A8)** unlocks end-to-end integer matmul, which only pays when you are compute-bound at large batch.

Weight-only 8-bit (W8A16) is the safest first move: roughly halves the footprint versus 16-bit with essentially no measurable quality loss and no activation calibration to get wrong.

At 4 bits, prefer **asymmetric** quantization. A symmetric quantizer centres its range on zero and wastes levels when the weight distribution is skewed; a zero-point offset (or per-group min/max) uses all 16 levels. Treat symmetric W4A16 as a prototyping baseline, not a shipping configuration.

Activations are the hard axis because transformers emit occasional very large values that force a wide quantizer range, cramming normal values into a handful of levels. SmoothQuant's answer is to move the difficulty rather than solve it — scale outlier activation channels down and the matching weight channels up, a mathematically equivalent but numerically friendlier transform.

### Formats: FP8, INT8, INT4, GGUF

- **FP8** is the least-regret production choice *when the silicon executes it natively* (Hopper-class and later). It is memory-cheap and compute-fast rather than a pure memory trade, and reported quality sits very close to BF16. On hardware without FP8 tensor cores it buys nothing.
- **INT8** is the portability fallback: same 1 byte per parameter, slightly coarser fit to the weight distribution, works on older GPUs. One benchmark found INT8 showed no clear advantage over FP8 where both were available.
- **INT4** is the capacity play. It roughly quarters the weight footprint and is where the accuracy conversation gets serious.
- **GGUF** (llama.cpp / Ollama) is a workstation and edge format. Its distinguishing feature — spilling layers into system RAM when VRAM runs out — is exactly what caps throughput, so it is the wrong answer for multi-tenant production serving. "Running GGUF" is also underspecified without the level: the high-K levels sit near full quality, the common 4-bit default is a visible step down, and the 2-bit levels degrade obviously.

Production systems increasingly run **mixed precision** — sensitive layers kept high, tolerant layers compressed hard — rather than one bit-width everywhere.

### Methods: AWQ, GPTQ, and the calibration set

Both are post-training quantization (PTQ): no retraining, one calibration pass, a second artifact to version alongside the base weights.

- **AWQ** reads importance off *activation* statistics rather than raw weight magnitude, identifies the small fraction of channels whose perturbation most damages output, and pre-scales them (folding the inverse into the model) so inference stays uniformly low-bit. That non-uniform allocation is why it beats naive uniform INT4.
- **GPTQ** quantizes greedily layer by layer and compensates: after rounding a weight or group, it nudges the still-unquantized weights to keep the layer's output close to full precision, guided by an approximate Hessian. One-shot and fast — a 175B model reportedly compressed to 3–4 bits in a few GPU-hours.

Both need a calibration set of a few hundred representative sequences, and both can overfit it — GPTQ has been observed showing mild degradation on out-of-distribution inputs. Calibration-set provenance is a design decision, not a hyperparameter copied from a blog. Use sequences that look like your production traffic.

A wider ladder exists when PTQ is not enough: **PTQ → dynamic quantization** (activations quantized at runtime; suits CPU) **→ static** (calibration dataset, lower latency) **→ QAT** (quantization simulated during training; the fallback when 4-bit degradation is unacceptable and you can afford a training run).

### Accuracy loss is task-shaped — the sources disagree on the number, not the shape

This is the least settled area in the material, and the disagreement is worth carrying explicitly.

- A hardware vendor's guide reports aggregate retention figures — roughly 99% for FP8, 97–98% for INT8, 94–96% for AWQ INT4, 93–95% for GPTQ INT4 — as if the loss were a scalar property of the format.
- A single-GPU benchmark of a 32B model measured something quite different: at INT4, a broad knowledge benchmark fell only ~1.6 points while a code benchmark fell ~8 points (roughly a fifth of its score), with math essentially flat and engineering and law the weakest knowledge categories. FP8 lost ~0.6 points on knowledge and was identical on code.
- A third source reports that lower precision disproportionately damages reasoning, code generation, extraction accuracy, long-context retrieval, and domain vocabulary — and that the damage shows up first in confidence calibration and rare-token generation rather than in aggregate perplexity.

The safest synthesis: **the aggregate retention percentages are sizing heuristics, not quality guarantees, and they systematically understate the damage to the tasks people actually build agents around.** A code-generation endpoint and a knowledge-retrieval endpoint should not inherit the same precision default. The eval suite, not the memory graph, is the gate on how far you compress — and it must diff full-precision against quantized output on real production prompts, real retrieval payloads, and real tool outputs, not on a public leaderboard.

Also note that the *speed* rankings conflict across hardware. One benchmark suite found 4-bit variants roughly halved end-to-end latency while 8-bit-activation schemes were consistently *slower* at low concurrency — yet on the same 70B model, the 8-bit schemes gave the best throughput at high concurrency. A single headline number picks the wrong scheme. Measure GPU memory, TTFT, ITL, end-to-end latency, and throughput across your real concurrency range, and expect the ordering to change between them.

### Quantization's real payoff is often concurrency, not latency

The memory freed from weights does not vanish — it becomes KV cache. In one single-GPU measurement, moving a 32B model from BF16 to INT4 grew the available KV pool from roughly 4 GB to roughly 47 GB, taking concurrent 4K-context sessions from a handful to a few dozen and cutting cost per million output tokens by more than half. The latency improvement was real but secondary.

Frame quantization proposals in those terms: *how many more concurrent sessions does this card now hold*, not *how many milliseconds did we save*.

### Pruning: only structured pruning speeds up a dense GPU

- **Unstructured pruning** zeroes scattered individual weights, keeps matrix shapes intact, and gets good quality-per-byte — and buys **no GPU speedup**, because dense tensor cores multiply straight through the zeros. You get a smaller file, not a faster server.
- **Structured pruning** removes whole attention heads, neurons, or layers. The shape changes, dense matmul still applies, and the throughput gain is real.
- **The hardware exception**: some GPU generations accelerate a rigid 2:4 sparsity pattern (exactly two of every four consecutive weights zero), quoted at close to 2× on sparse operations — and worth nothing if the sparsity does not satisfy the constraint exactly.
- **CPU inference inverts the rule**: CPU serving is memory-bandwidth bound, so skipping zero weights genuinely helps because less data must be loaded.

Named methods worth recognising: magnitude pruning (cheap; iterative prune-then-finetune beats one-shot, but magnitude is a proxy for importance rather than importance); Wanda (scores a weight by magnitude × input-activation norm, so a small weight feeding a hot neuron survives; minutes to run, no gradients); SparseGPT (reuses second-order machinery to correct surviving weights, and can prune and quantize in one pass); and layer-dropping approaches that remove whole blocks whose output barely differs from their input — redundancy concentrates in the middle of the network, not at the ends. Early exit is the inference-time version: stop at an intermediate layer when confidence is already high, so easy inputs pay less.

### Speculative decoding: lossless on quality, conditional on economics

A small fast **draft** model proposes several tokens ahead; the large **verifier** checks them in one parallel forward pass, accepting a run of tokens for roughly the cost of generating one. Rejection falls back to the verifier's own token, so with the full-size model as verifier the output distribution is the target model's — a modified-rejection-sampling argument, not an approximation. Sources agree this makes it the rare optimization that costs no quality, though one notes the practical hedge that serving stacks describe it as *algorithmically* lossless with caveats around hardware numerics.

**Acceptance length — the mean number of drafted tokens accepted per verifier pass — is the governing metric.** Everything else follows from it.

- **Task predictability decides the win, not model size.** One reported case study measured acceptance length ~4.9 on a coding benchmark (with roughly 4× lower inter-token latency, holding across request rates) versus ~2.5 on summarization, where the speedup shrank as request rate rose. Code is predictable; creative prose is not.
- **It can be a pessimization.** Many in-flight requests plus a short acceptance length means the drafting work is pure overhead and the server gets *slower*. The profile it wants is medium-to-low QPS, memory-bound serving, long responses — internal assistants, analyst tools, document workflows, agentic chains. Short answers at high concurrency erode the gain.
- **Distribution match drives acceptance.** A speculator performs best on data resembling its training distribution, including chat-template shape. An English-trained speculator on multilingual traffic is a documented way to make things worse; fine-tuning or training a speculator is a real deployment step, not an optional extra.
- **Long context is a known weak spot** — treat long-context workloads as needing their own measurement.
- **The draft model's own latency becomes the new floor.** It must be fast before it is accurate.
- **Composition with quantization**: the sources both agree it composes and disagree on process. One reports quantized-verifier plus speculator as a near-lossless stacked speedup; another explicitly forbids shipping quantization and speculative decoding in one deploy, because precision loss and acceptance rate interact in ways that hide regressions. A third gives a default recipe of **quantized target, full-precision draft** — degrading the draft costs acceptance, which is the thing you cannot afford to lose. Reconcile them by benchmarking each lever separately and shipping them in separate changes, then measuring the combination.

If acceptance length is near 2 and your request rate is high, the answer is no.

### Batching and memory layout

- **Continuous batching** re-makes the admission decision every decode step, so a slot freed by a finished request is refilled immediately instead of idling until the slowest member of a static batch completes. This is table stakes in modern serving frameworks; verify it is on before engineering anything else.
- **Batch size is the explicit knob** behind the per-user-latency versus system-throughput tension. An interactive assistant and an offline summarisation job are tuned in opposite directions from the same config file.
- **PagedAttention** stores the KV cache in small fixed-size blocks (commonly ~16 tokens) addressed through a block table, instead of one contiguous per-request reservation sized for the worst-case answer. It eliminates reservation waste — and, critically, it is what makes cross-request block sharing physically possible.
- **Efficient attention kernels** (FlashAttention-class) reorder long-prompt processing for speed with identical output and ship enabled by default in many frameworks. Check whether you already have the free prefill win before building anything.

### The KV cache is the capacity constraint

It starts at prompt size and adds an entry per generated token, per sequence. Across many concurrent long-response requests it can exceed the model's own weights several times over. Every decode step reads all of it. Two consequences:

- **Concurrency is a KV-memory question**, which is why weight compression converts directly into user capacity (above).
- **Peak memory, not steady-state memory, is the binding constraint.** Any scheme that shrinks the cache only *after* the full context has been prefilled still requires the full cache to exist at some instant. Block-wise prefill — ingesting in blocks and compressing as you go — is what converts an unbounded peak into a fixed budget.

**Debugging trap**: GPU memory that plateaus immediately after startup is usually the framework's pre-allocated KV pool, not a full cache or an idle GPU, and device-level tools cannot show KV growth *inside* that reservation. The framework's own startup log is the source of truth. Teams misread this and add GPUs or disable features chasing a bottleneck that is not there. Relatedly, lowering a `gpu-memory-utilization`-style knob looks like it frees memory but can silently cap batch size or force paging, hurting decode more than the returned memory was worth.

**Multi-GPU caveat**: under tensor parallelism, prefill amortises its collective communications across one or a few passes while decode re-fires them on every generated token. Adding GPUs to solve a memory problem can manufacture a communication-bound decode problem.

### Prefix caching: reuse the prefill you already paid for

If two requests share a leading span of tokens, the KV blocks for that span are identical and need not be recomputed. The enabling identity claim is simple: **a fixed-size block of KV entries is uniquely determined by the tokens inside it plus all tokens preceding it.** That collapses what looks like a tree problem into a flat hash table — logical block → hash → physical block — with blocks staying mutually independent and individually allocated, so ordinary cache machinery applies.

In practice the key is a **chained hash**: parent block's hash + the exact token IDs in this block + an "extra hashes" component covering anything else that changes the tensor values. Two requests can only share block N if they shared blocks 0..N−1, which is exactly the reuse semantics you want. Hashing the token tuple alongside the parent hash is deliberate redundancy against collisions.

Design implications for prompt layout:

- **Only full blocks are cached, and matching is block-granular.** A shared prefix ending mid-block yields no hit for that block. Put the invariant part of the prompt first — system instructions, few-shot examples, the retrieved document — and, where you can, align it to block boundaries.
- **Prefix caching degrades to a full prefill when nothing is shared.** It is not a general speedup; it is a reward for stable prompt structure.
- **It is a complement to, not a substitute for, semantic caching.** Prefix reuse only shrinks repeated prompt-processing work; a semantic cache sits above the inference stack and can skip the model entirely on a hit, erasing both prefill and decode. Semantic caching trades correctness risk for latency — a too-loose similarity threshold serves the wrong answer — and is inappropriate wherever every response must be freshly grounded or personalized. See `redis-caching-patterns` for that layer.

### Prefix cache keys are a correctness and tenancy boundary

Because the hash *is* the cache key, hash quality is a security property, not a performance knob.

- **Anything that changes the computed KV values but is invisible in the token IDs must be folded into the key.** Documented examples: LoRA adapter IDs, multimodal input hashes, and an explicit cache salt. Miss one and you serve another request's tensors. Folding the LoRA ID in also lets one cache serve many adapters jointly, raising the global hit rate.
- **Multimodal inputs force explicit hashing.** An image collapses to a run of identical placeholder tokens after tokenization, so token IDs alone cannot distinguish two different images; the image processor's own hash must ride in the extra-hash field on every block the placeholders span.
- **A per-request salt is the trust-group boundary.** Only requests presenting the same salt can hit each other's blocks. The threat it defends against is timing inference — an adversary probes prefixes and reads latency differences to learn what someone else submitted. If untrusted tenants share one engine, either set distinct salts per trust group or accept a side channel, knowingly.
- **Do not downgrade to a fast non-cryptographic hash to buy throughput** unless the tenancy model makes collisions harmless. Collisions here mean undefined behaviour or cross-tenant content leakage, not a slow request.
- **Pick a serialization that is stable across versions** if hashes must survive a deployment — an external KV store or cross-version reuse needs a language- and version-stable encoding, not a language-native pickling default.

### Eviction and admission — the scheduler creates the locality

The default eviction policy for a prefix cache is reasonable: evict only blocks whose reference count is zero, prefer least-recently-used among them, and break ties by evicting the block at the end of the longest prefix (deepest blocks are least likely to be reused). Reference counting matters — an in-use cached block must be "touched" out of the free queue rather than evicted underneath a live request.

But there is a sharper point that cuts against LRU as a default. **LRU was designed for caches with an unknown future; a serving queue is a known future.** The requests waiting in line are a structured prediction of the demand about to arrive, and one research system exploits this by building an incremental prefix tree over the *pending queue* and using it for both admission ordering and eviction scoring. Its findings, worth internalising even if you never adopt the system:

- **Admission ordering is the dominant lever; eviction only refines it.** A cluster-aware admission sort alone lands within a few percentage points of the full system; the eviction hook adds 0–3% on one engine and nothing on another. Eviction cannot manufacture temporal locality the scheduler never created.
- **Scheduling-induced thrashing is real.** With interleaved tenants and a cache too small to hold two prompts, arrival-order admission prefills, evicts, and refills the same prefixes for a 0% hit rate; reordering the identical requests by prefix cluster reached ~62%.
- **Locality optimisations starve the unshared minority — budget for that explicitly.** Grouping cluster members contiguously bought almost no extra hit rate but cost 10–29% on TTFT and end-to-end latency by deferring singleton requests. A fairness lane that widens as singletons age recovered much of it.
- **Guard the optimisation so it costs nothing when it cannot pay.** A cheap check for "is there any exploitable prefix sharing here at all" that short-circuits the machinery keeps no-structure workloads within ~1.5% of the naive baseline. Prove no-regress on the workloads you do not help.

### Long conversations: episodic compression

Long-running conversational assistants hit a memory wall unrelated to the model's advertised context length — the KV cache grows linearly with dialogue history, so a fixed memory budget runs out well before the context window does. Two obvious mitigations are each broken in a specific way: compressing *after* full prefill still requires materialising the full cache (unbounded peak), and evicting based on the *current query* narrows the cache's semantics to one question and fails on the follow-up.

The alternative studied in the material is to make the compression unit a **topical episode**: cluster the history into coherent segments, build one compressed snapshot per episode, and retrieve only the relevant snapshot at query time, so total memory stays flat as the conversation grows. Two secondary findings generalise: **layers are not equally compressible** (distribute the budget unevenly toward the layers that degrade most), and it is training-free, so it is a serving change that can be reverted per deployment rather than a model change.

Costs are real: an episode-clustering step, per-episode snapshot storage, a retrieval step in the query path, and a new failure mode where the selected episode is the wrong one and the model answers from a cache missing the needed turns. Reported figures (roughly 4–6× compression near full accuracy, with latency and peak-memory reductions) come from long-*conversation* QA benchmarks, not long-document ones — single-pass document evals will not surface the multi-turn failure this targets. If the quality bar cannot tolerate any recall loss on old turns, buy memory instead.

### Giving each phase its own lane

When prefill and decode share one GPU and one I/O path they contend: an incoming prefill can block in-flight decode streams and make already-streaming responses stutter, and a long prefill inflates TTFT for everything queued behind it. At least one early framework policy prioritized prefill to improve TTFT and consequently starved decode. Two structural remedies:

- **Chunked prefill** splits a long prompt into segments, caches each segment's KV, and lets decode steps run between chunks. It deliberately makes TTFT slightly worse to stop long prompts monopolising the GPU, with substantial reported aggregate throughput gains. Wrong default for a latency-obsessed single-user demo; right default for a shared server.
- **Disaggregated serving** puts prefill and decode on separate GPU pools, each scaled and tuned for its own profile. Published research reports large gains (multiples of served requests, or much tighter SLO adherence, versus colocation) and several large operators run it. The costs: a network hop to move KV cache between pools, and two fleets to capacity-plan and fail over independently. Unjustifiable below meaningful concurrency.

Shared I/O queues cause the same problem one layer down — a single metadata path lets a bandwidth-hungry prefill stall a latency-sensitive decode. Note that the strongest version of this argument in the material comes from a storage vendor; the phase asymmetry and the published research stand on their own, but treat "and therefore buy this storage layer" as vendor framing of a real problem.

### Measuring: the discipline that makes numbers trustworthy

- **Isolate before you attribute.** Restart the server so counters reset, issue one request with a fixed prompt and a fixed output-token budget, no concurrent traffic. Modern serving frameworks expose per-phase timing histograms; turn them into per-request average prefill and decode times over a window.
- **Then load-test with captured traffic.** Synthetic loads are for isolating a component or comparing hardware. Capacity claims need real workloads with mixed prompt lengths, genuine concurrency, and sustained runs. Generating that load is `load-testing` territory.
- **Use a tool ladder, in order**: metrics/dashboards for trends → device-level memory tooling for sanity checks → collective-communication debug output to confirm per-token collectives under tensor parallelism → a systems profiler for idle gaps in the timeline → a kernel profiler only once you know which kernel is slow.
- **Evaluate across six axes before shipping any of this**: latency (TTFT, ITL, full response), throughput under realistic concurrency and burst, cost (GPU memory, GPU count, utilisation, batching, autoscaling), quality (accuracy, groundedness, extraction fidelity, refusal behaviour, reasoning depth), reliability (prompt variance, long-context behaviour, rollback path), and operations (deploy, versioning, compatibility, observability, incident response).

### If you consume a hosted API

Most of the above is not yours to tune — the provider owns precision, batching, kernels, and the decode path. What survives:

- **The vocabulary and the instrumentation.** Record TTFT and inter-token latency as separate series rather than one end-to-end timer; it tells you whether a long system prompt or a long output is the problem. `langfuse-llm-tracing` covers per-call capture.
- **Context discipline.** A long prompt costs superlinearly at prefill. Prune retrieved context; do not pad the system prompt.
- **Prompt layout for the provider's prefix cache.** Same rule as self-hosting — invariant content first, volatile content last.
- **Output-length control.** For long-output workloads, output length owns total latency.
- **Application-level caching** (exact-match and semantic), which can skip the model entirely.
- **Model-tier selection**, which is the hosted equivalent of the quantization/distillation trade — with the same obligation to gate it on a task-shaped eval.

## Anti-patterns to avoid

1. **Reporting one "latency" number for a generation endpoint** — it hides which phase is failing and guarantees the next optimization is aimed at the wrong one. Instrument TTFT and inter-token latency separately, and alert on the tail.
2. **Optimizing the phase that isn't the bottleneck** — quantizing weights to fix a two-second prefill on a RAG endpoint, or adding prefix caching to a code-generation stream whose pain is decode.
3. **Saying "we quantized it"** — without the WxAy scheme, the method, and the calibration set, the statement is unfalsifiable and unreviewable.
4. **Treating aggregate retention percentages as a quality guarantee** — the sources conflict, and the aggregate numbers systematically understate damage to code generation, multi-step reasoning, extraction, and long-context retrieval. Gate on your own eval set, on real production prompts.
5. **One precision default across every endpoint** — a knowledge-lookup endpoint tolerates INT4 that a code-generation agent does not.
6. **Copying benchmark numbers across hardware** — several sources state plainly that their configurations were not tuned for peak performance and exist to show relative ordering. The 8-bit-is-slower and 4-bit-is-faster results are properties of specific hardware and serving stacks.
7. **Quantizing a model that already fits with headroom** — the compression buys nothing and adds a variable to debug.
8. **Shipping quantization and speculative decoding in one change** — precision loss and acceptance rate interact in ways that hide regressions. Benchmark each separately, ship separately, then measure the combination.
9. **Turning speculative decoding on globally** — under high concurrency with low acceptance length, drafting is pure overhead and the server gets slower. Measure acceptance length on your traffic first.
10. **Degrading the draft model to save memory** — the draft's latency is the new floor and its distribution match drives acceptance; the usual recipe is a compressed target with a full-precision draft, not the reverse.
11. **Expecting unstructured pruning to speed up a GPU** — dense tensor cores multiply through the zeros. You get a smaller file. Structured pruning (or an exactly-conforming hardware sparsity pattern) is what buys throughput.
12. **Reading a flat GPU-memory graph as an idle GPU** — that plateau is almost always the pre-allocated KV pool. Read the framework's startup log before adding hardware.
13. **Adding GPUs to fix a decode problem** — under tensor parallelism, decode re-fires collective communications every token; more GPUs can convert a memory bottleneck into a communication bottleneck.
14. **Volatile content at the head of the prompt** — a timestamp, request ID, or user name before the system prompt destroys every prefix-cache hit downstream of it.
15. **Prefix cache keys that omit a KV-changing input** — a missing LoRA ID, image hash, or tenant salt means serving another request's tensors. Treat the key as a correctness boundary, not a performance knob.
16. **Sharing one prefix cache across untrusted tenants without salting** — cache-hit latency differences are a readable side channel for what someone else submitted.
17. **Tuning eviction to fix a hit rate the scheduler destroyed** — admission ordering dominates; eviction cannot manufacture locality that never existed.
18. **Locality optimisation without a fairness lane** — grouping requests by shared prefix starves the unshared minority, with double-digit TTFT cost for those requests.
19. **Validating an eviction policy on single-turn evals** — query-dependent eviction looks excellent single-shot and fails on the follow-up turn.
20. **Optimizing the decode loop when the time is spent outside it** — none of these techniques fix a system whose latency is retrieval, tool-call round trips, or an oversized context assembled upstream.

## References

Digests (own-words summaries of the sources, in `references/`) — each file's frontmatter names its source and author:

- [aie-038-accelerating-llm-inference-with-post-training-quantization.md](references/aie-038-accelerating-llm-inference-with-post-training-quantization.md) — WxAy notation, AWQ vs GPTQ, SmoothQuant, measured memory/latency/throughput across three models and concurrency 1–128
- [aie-039-llm-quantization-explained-int4-int8-fp8-awq-and-gptq.md](references/aie-039-llm-quantization-explained-int4-int8-fp8-awq-and-gptq.md) — bytes-per-parameter sizing, format vs method, aggregate retention figures, GGUF as a workstation format, QLoRA/NF4
- [aie-040-llm-quantization-bf16-vs-fp8-vs-int4.md](references/aie-040-llm-quantization-bf16-vs-fp8-vs-int4.md) — single-GPU benchmark showing task-shaped accuracy loss and quantization's concurrency payoff (KV pool growth, cost per million tokens)
- [aie-041-improving-the-economics-of-llm-inference-with-speculative.md](references/aie-041-improving-the-economics-of-llm-inference-with-speculative.md) — speculator/verifier roles, acceptance length as the governing metric, coding vs summarization case study, pessimization under load
- [aie-042-speculative-decoding-quantization-and-distillation-tradeof.md](references/aie-042-speculative-decoding-quantization-and-distillation-tradeof.md) — diagnose-the-bottleneck framing, distillation as a model-product decision, the six evaluation axes, do-not-stack-in-one-deploy rule
- [aie-043-speculative-decoding-and-quantization-llm-inference.md](references/aie-043-speculative-decoding-and-quantization-llm-inference.md) — losslessness as a distribution theorem, quantized-target/full-precision-draft default, where quantization damage shows up first
- [aie-044-prefill-and-decode-a-technical-guide-to-the-two-phases-of.md](references/aie-044-prefill-and-decode-a-technical-guide-to-the-two-phases-of.md) — the phase split, arithmetic intensity and utilisation figures, perceptual latency thresholds, disaggregated serving, chunked prefill
- [aie-045-prefill-vs-decode-llm-inference-phases-explained.md](references/aie-045-prefill-vs-decode-llm-inference-phases-explained.md) — ITL derivation, workload-shape mapping, phase contention and scheduling, prefix vs semantic caching, decode-lever figures
- [aie-046-prefill-vs-decode-llm-inference-optimization.md](references/aie-046-prefill-vs-decode-llm-inference-optimization.md) — the TTFT + (N−1)×TPOT formula, batch size as the latency/throughput knob, continuous batching, PagedAttention vs prefix caching
- [aie-047-llm-inference-optimization-prefill-vs-decode.md](references/aie-047-llm-inference-optimization-prefill-vs-decode.md) — per-phase measurement discipline, the pre-allocated-KV-pool debugging trap, tensor-parallel decode collectives, tool ladder
- [aie-048-the-llm-inference-optimization-stack-quantization-to-specu.md](references/aie-048-the-llm-inference-optimization-stack-quantization-to-specu.md) — structured vs unstructured pruning, 2:4 sparsity, Wanda/SparseGPT/layer-dropping, the PTQ→dynamic→static→QAT ladder, mixed precision
- [aie-049-automatic-prefix-caching-design-in-vllm.md](references/aie-049-automatic-prefix-caching-design-in-vllm.md) — chained block hash, extra-hash extension point, cache salt as tenancy boundary, hash-algorithm security axis, block pool and free-queue mechanics
- [aie-050-peek-predictive-queue-informed-kv-cache-management-for-llm.md](references/aie-050-peek-predictive-queue-informed-kv-cache-management-for-llm.md) — the pending queue as a demand signal, admission ordering dominating eviction, scheduling-induced thrashing, the fairness-lane cost
- [aie-051-epicache-episodic-kv-cache-management-for-long-term-conver.md](references/aie-051-epicache-episodic-kv-cache-management-for-long-term-conver.md) — peak vs steady-state memory, block-wise prefill, episodic compression units, layer-uneven budgets, multi-turn eviction traps
- [aie-052-automatic-prefix-caching-implementation-details-vllm.md](references/aie-052-automatic-prefix-caching-implementation-details-vllm.md) — the block-identity claim that collapses prefix reuse into a flat hash table, LoRA-in-the-hash, default eviction policy
- [aie-053-understanding-vllm-kv-cache.md](references/aie-053-understanding-vllm-kv-cache.md) — the scheduler's per-request call sequence, block pool vs memory pool terminology, assignment vs tensor-write separation

Attribution: all digests are own-words summaries of the third-party articles, documentation, and papers named in their frontmatter; no source text or code is reproduced. Vendor-authored sources are flagged inline above where their framing is self-interested.

Related skills:

- `performance-optimization` — general service profiling and hot-path work; use it for the parts of the request that are not the model
- `load-testing` — generating the realistic sustained concurrency any capacity claim here depends on
- `redis-caching-patterns` — the application-level cache tier above the model (exact-match and semantic response caching, invalidation, stampede protection)
- `langfuse-llm-tracing` — per-call LLM telemetry: latency, token usage, cost attribution, model/provider labelling
- `observability-and-logging` — dashboards, SLOs, and alerting for the serving tier as a whole
