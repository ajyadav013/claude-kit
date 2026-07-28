---
source: https://billtcheng2013.medium.com/llm-fine-tuning-7986bb8e939f
author: Xin Cheng (Medium)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Fine-tuning is the ladder's last rung; PEFT makes it cost adapters, not GPUs

## What it adds beyond the primary

This is an annotated link-roundup rather than an argued piece, so its value is
the map: it lays out the whole adaptation ladder (plain prompting, few-shot,
prompting plus retrieval, chain-of-thought, self-consistency, tree-of-thoughts,
prompt tuning, then fine-tuning) and says to walk it top-down and stop as soon
as you are satisfied. Where the cluster primary is about generating training
data by curating production traffic, this one covers the mechanics on the far
side of that data — what full fine-tuning costs, what parameter-efficient
methods substitute for it, and what quantization buys at inference. It also
carries the negative result the primary does not: fine-tuning does not fix a
knowledge cutoff (it only moves the cutoff later), does not make a model cite
sources, and gives you no per-user access control, because every caller of a
fine-tuned model reaches all of the knowledge baked into it. That is the
argument for keeping retrieval in the design even after you fine-tune, and it
is a design constraint, not a tuning detail.

The concrete adaptation taxonomy worth keeping:

- **Full fine-tuning** updates every layer. Expensive, and it risks
  catastrophic forgetting of general capability.
- **PEFT** freezes most of the network and trains a small subset. The roundup
  reports it also does better in low-data regimes and generalises better
  out-of-domain than full fine-tuning, and that compact checkpoints make it
  portable.
- **LoRA** injects trainable low-rank matrices, classically at the attention
  query and value projections, on the hypothesis that the useful weight update
  is intrinsically low-rank. The arithmetic example given: a 1000x1000 update
  matrix factored as 1000x8 times 8x1000 drops 1,000,000 trainable parameters
  to 16,000. Two knobs matter — rank `r` and scaling `alpha`, with the
  effective contribution scaled by alpha/r; too small under-adapts, too large
  destabilises training. One reported experiment sweep found alpha at twice
  the rank (r=256, alpha=512) worked best.
- **Adapters** add small trainable layers between frozen transformer layers.
  The operational point is swappability: one base model plus one small adapter
  per task, so 100 downstream tasks means 100 adapters, not 100 model copies.
  LoRA weights can alternatively be merged back into the base weights to avoid
  paying extra inference latency.
- **Prefix / prompt tuning** learns soft virtual tokens prepended to the input
  and leaves the model untouched. Reported to beat hand-written hard prompts,
  but the learned prompts are not interpretable.
- **Instruction tuning and RL-based alignment** (RLHF, and the PPO / DPO /
  GRPO line) sit on top for instruction-following and preference alignment.
- **RAFT** fine-tunes the model specifically to work with retrieved context,
  training it to ignore distractor documents.

Measured numbers reported for the cost claim, useful as order-of-magnitude
anchors rather than benchmarks: Falcon-7B training dropping from roughly 8h52m
to 1h09m and 40GB to 16GB under LoRA; one Lightning comparison at 6685.75s and
21.33GB for bf16 LoRA versus 10059.53s and 14.18GB for QLoRA with nf4 — so
QLoRA trades roughly half again as much wall time for about a third less
memory. QLoRA loads the base in 4-bit (nf4, with the quantization constants
themselves quantized) while keeping the LoRA adapters in higher precision to
limit quantization error, dequantizing to higher precision for the actual
forward and backward passes. The claimed effect on hardware: Falcon-40B from
90GB of VRAM to 45GB, Falcon-7B to under 10GB, and a 65B model that would need
over 780GB (about ten 80GB A100s) for standard fine-tuning becoming a
single-A100 job.

On quantization proper it distinguishes post-training quantization from
quantization-aware training, and separates the deployment formats by target:
GPTQ works layer-by-layer for GPU inference, AWQ is activation-aware and
preserves the weights most critical to quality (reported as the better 4-bit
option and good on edge devices), and GGUF targets CPU inference via
llama.cpp. It notes bf16 as effectively a truncated fp32 that keeps fp32's
dynamic range, unlike fp16, and contrasts symmetric mapping around zero with
asymmetric/affine mapping of an arbitrary min-max range. Size anchor: one
model at over 13GB in base precision, about 5GB at 5-bit and about 4GB at
4-bit.

Finally, the gate. The roundup cites a position holding that most teams
probably do not need to fine-tune at all: only reach for it when accuracy
requirements are stringent enough to justify sustained engineering and ops
cost, or when you need fast local/edge inference (and even then a smaller
encoder-style model may be the better answer), or when few-shot plus RAG
together still fall short. It also flags an imitation-data failure mode —
piling on data imitating a stronger model can degrade the student, which
learns the teacher's style rather than its content — and frames in-context
learning versus fine-tuning as meta-gradients at inference time versus real
gradients written into weights, with ICL bounded by how many examples you
can afford to carry in the prompt.

## Primary source for this cluster

[aie-059-distillation-with-programmatic-data-curation-cheaper-infer.md](aie-059-distillation-with-programmatic-data-curation-cheaper-infer.md)

## Fidelity check

1. Claim: the article presents an escalation ladder from prompting through
   few-shot, retrieval, chain-of-thought, self-consistency, tree-of-thoughts
   and prompt tuning to fine-tuning, to be walked top-down. Support: the
   capture opens its Basics section with exactly that ordered list and the
   instruction to consider the approaches from top down until satisfied.
