---
source: https://redpumpkin.ai/blog/speculative-decoding-quantization-and-distillation-tradeoffs
author: Yudhi Pratama — Redpumpkin.AI
license-note: ideas absorbed in own words; no text or code reproduced
---

# Speculative decoding, quantization, and distillation fix different bottlenecks

## What it teaches
Teams that get a model working in testing hit one of three walls in production:
the responses feel slow, the serving bill is too high, or a general model is
overkill for a narrow repeated workflow. Three optimization paths address these
walls, and they operate on different layers of the system. Speculative decoding
changes the *decoding loop* — a small draft model proposes several tokens and
the large target model verifies them in one parallel forward pass instead of
generating serially. Quantization changes *numerical representation* — weights
and activations move to FP8, INT8, or INT4, shrinking memory footprint and
widening the set of devices a model fits on. Distillation changes *the model
itself* — a smaller student is trained to imitate a larger teacher, usually
scoped to one task or domain. The article's core discipline is that the choice
must follow the measured bottleneck, and that combining techniques is safe only
after each has been benchmarked separately, because precision loss, draft
acceptance rate, and task-specific quality interact in ways that hide
regressions.

## Key patterns & decisions
- **Diagnose the bottleneck before choosing the technique** — Slow token
  generation with acceptable quality points at speculative decoding. Memory
  pressure or cost-per-request points at quantization. A stable, high-volume,
  narrow task points at distillation. The fastest pilot is the wrong answer if
  it does not move the constraint that actually binds.
- **Speculative decoding preserves output distribution, so it is a latency
  lever, not a behavior change** — The original ICML work reported 2x–3x
  acceleration with identical outputs on T5-XXL. vLLM documents its path as
  algorithmically lossless for supported modes, with practical caveats around
  hardware numerics. That makes it the low-blast-radius option when the target
  model already passes quality gates.
- **Speculative decoding's payoff is workload-shaped** — vLLM positions it for
  medium-to-low QPS, memory-bound serving, the profile of internal assistants,
  analyst tools, document workflows, and agentic systems producing long
  responses. Short answers, high concurrency, compute-bound serving, or a weak
  draft model erode the gain. NVIDIA measured above-3x speedups in TensorRT-LLM
  for selected Llama target/draft pairs on H200 (November 2024) — i.e. gains
  are configuration-specific, not universal.
- **Draft acceptance rate becomes a first-class production metric** — Adding a
  second model to the serving path means monitoring acceptance rate, latency
  variance, memory pressure, and new failure modes. Serving-stack
  compatibility is a real constraint: vLLM documents feature incompatibilities
  and version-bounded support, including limits with some parallelism
  configurations.
- **Quantization buys placement flexibility, which is an architecture
  decision** — SmoothQuant reported up to 1.56x speedup and 2x memory
  reduction with preserved accuracy in its experiments. vLLM lists hardware
  compatibility across AWQ, GPTQ, FP8, INT8, BitsAndBytes, and GGUF, and
  Hugging Face TGI supports GPTQ, AWQ, bitsandbytes, EETQ, Marlin, EXL2, and
  FP8. Hardware fit should therefore be a design criterion up front, not a
  discovery made at deploy time.
- **Quantization quality regression is task-specific and invisible to generic
  benchmarks** — Lower precision disproportionately hurts reasoning, code
  generation, extraction accuracy, long-context retrieval, and domain
  vocabulary. The release gate must diff full-precision against quantized
  output on the tasks users actually run, not on a public leaderboard.
- **Distillation is a model-product decision, not an inference switch** — It
  creates a new artifact the team must validate, version, govern, and own the
  drift of. It needs a training pipeline, dataset strategy, and eval harness,
  so the work relocates from serving optimization into model development.
- **Specialization narrows behavior and inherits teacher defects** — Research
  on specializing small models for multi-step reasoning found target-task gains
  traded against broader generic ability. Separately, a biased, brittle, or
  policy-inconsistent teacher transfers those patterns to the student unless
  the training set is filtered and tested. Counterweight: Distilling
  Step-by-Step reported a 770M T5 beating a 540B PaLM on one benchmark by using
  rationales as extra supervision — strong signal can beat raw scale on a
  narrow contract.
- **Evaluate on production traces across six axes** — Latency (TTFT,
  inter-token, full response), throughput under realistic concurrency and
  burst, cost (GPU memory, GPU count, utilization, batching, autoscaling),
  quality (accuracy, groundedness, extraction fidelity, refusal behavior,
  reasoning depth), reliability (prompt variance, long-context behavior,
  rollback path), and operations (deploy, versioning, compatibility,
  observability, incident response). The eval set should carry real prompts,
  real retrieval payloads, real tool outputs, and the failure examples the
  business cares about.

## When to apply / trade-offs
This applies when a team owns its inference stack — self-hosted or dedicated
serving on vLLM, TGI, or TensorRT-LLM — and has an inference bill or latency
SLO it can actually move. It is largely inapplicable to teams consuming a
hosted API such as Anthropic's or OpenAI's, where the equivalent levers are
model-tier selection, prompt caching, and batching rather than precision
formats or draft models. The cost of following this guidance is real: it
demands production-trace benchmarking infrastructure before any change ships,
and it forbids the tempting shortcut of stacking quantization plus speculative
decoding in one deploy. Distillation in particular should not be attempted for
a workflow whose requirements are still moving — the training, governance, and
drift-ownership burden only amortizes over a stable, high-volume, narrow task.
Do not reach for any of the three when the actual bottleneck is upstream
(retrieval latency, tool-call round trips, oversized context) — none of these
techniques fix a system whose time is spent outside the decode loop.

## Fidelity check
1. Claim: speculative decoding reported 2x–3x acceleration with identical
   outputs on T5-XXL. Support: the capture states the original ICML paper
   reported 2x to 3x acceleration with identical outputs in T5-XXL
   experiments, attributing it to the target model validating multiple
   candidate tokens in one forward pass.
2. Claim: SmoothQuant reported up to 1.56x speedup and 2x memory reduction.
   Support: the capture states SmoothQuant reported up to 1.56x speedup and 2x
   memory reduction for tested LLMs while preserving accuracy in its
   experimental settings.
3. Claim: a 770M T5 outperformed a 540B PaLM on one benchmark via rationale
   supervision. Support: the capture describes Google's Distilling
   Step-by-Step work reporting a 770M T5 model outperforming a 540B PaLM model
   on one benchmark task by using rationales as additional supervision.
