---
source: https://aimultiple.com/llm-quantization
author: Ekrem Sarı and Sıla Ermut (AIMultiple)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Quantization's real payoff is concurrency, not latency

## What it adds beyond the primary

A single-GPU benchmark (Qwen3-32B, one H100 80GB, vLLM, batch size 1)
across four precisions — BF16, FP8, GPTQ-Int8, GPTQ-Int4 — measured on
MMLU-Pro (~12K questions, 5-shot) and HumanEval (164 problems, pass@1).
Two findings are load-bearing for anyone sizing self-hosted inference.
First, accuracy loss is task-shaped, not uniform: at Int4, MMLU-Pro fell
only 1.6 points (70.24% to 68.66%) but HumanEval fell 8 points (39.02% to
31.10%), with engineering (49.64% to 43.45%) and law (43.05% to 40.60%)
the weakest MMLU-Pro categories while math was essentially flat (81.87%
at BF16/FP8/Int8, 80.24% at Int4). So a code-generation agent and a
knowledge-retrieval agent should not inherit the same precision default.
Second, the headline win is capacity rather than speed: Int4 was 2.7x
faster than BF16, but the memory freed from weights moved KV cache from
4.4 GB to 47.3 GB — roughly 4 versus 47 concurrent users at 4K context,
and cost per 1M output tokens from $28.73 to $10.69 at $2.69/hr H100 SXM
pricing. The authors' default recommendation is FP8 (1.5x throughput,
half the memory, 0.6 points of MMLU-Pro, identical HumanEval to BF16,
and shipped by the model authors rather than a third-party checkpoint);
Int8 showed no clear advantage over FP8 here. The article also names its
own limits: batch size 1 only, H100-specific (A100/A10 lack native FP8),
community-provided GPTQ checkpoints, and GPTQ only — AWQ, NF4, GGUF and
HQQ untested.

## Primary source for this cluster

No primary digest exists on disk yet for the `quantization` cluster —
this stub is currently the only entry. It should be re-pointed at the
primary once one lands.

## Fidelity check

1. Claim: quantizing weights moved the KV cache from 4.4 GB to 47.3 GB,
   raising concurrency from roughly 4 to roughly 47 simultaneous users at
   4K context. Support: the capture reports both cache sizes and both
   user counts in the section on concurrency, sourcing them from vLLM
   engine initialization logs, and restates them in its conclusion.
