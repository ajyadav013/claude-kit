---
source: https://aclanthology.org/2025.findings-emnlp.930.pdf
author: Ukyo Honda, Soichiro Murakami, Peinan Zhang (CyberAgent) — Findings of EMNLP 2025
license-note: ideas absorbed in own words; no text or code reproduced
---

# Distilling demonstrations into one cheat sheet replaces the retriever

## What it adds beyond the primary

The inference-optimization captures in this collection treat long prompts as a
serving problem to be absorbed by prefix caching, KV reuse, or quantization.
This paper attacks the same cost from the prompt side and shows the cheaper
move is often to not send the demonstrations at all. The procedure is a
one-time offline preprocessing pass: give the model the entire demonstration
set plus a prompt asking it to extract the core knowledge needed for the task,
and keep the resulting textual summary. At inference the model sees only that
summary, two examples retained purely as output-format instructions, and the
test input. Three findings are load-bearing for anyone building an LLM feature.
First, the accuracy-per-token trade is decisive: averaged over the eight tasks,
the distilled sheet reached 90.0 accuracy at 2,036 input tokens where the
many-shot setting reached 91.0 at 42,461, and it beat 8-shot (87.1) at a
comparable budget. Second, it landed level with demonstration retrieval —
BM25 86.9, cosine-embedding 89.1, Set-BSR 89.0, all at roughly the same token
count — while removing the retrieval index, the per-request search, and the
requirement to keep the demonstration pool online. Third, and most useful in
practice, the artifact is human-readable and directly editable: on the one task
where the method failed (Disambiguation QA, where the model leaned on
world knowledge instead of answering "ambiguous"), the authors could read the
sheet, delete the section that encouraged commonsense inference, add an
explicit instruction against it, and move accuracy from 87.0 to 89.7. A pile of
demonstrations offers no comparable inspection or intervention surface. The
sheets also transferred across models — ones written by GPT-4.1 largely held up
under Gemini 2.0 Flash — and the technique survived removing rationale
augmentation, adding self-consistency decoding, and varying the distillation
prompt. Two honest limits temper adoption. The method only pays where many-shot
actually beats few-shot for that task and model; the authors selected their
eight BBH tasks precisely by that criterion (many-shot ahead by more than one
percentage point) and recommend a small-subset preliminary check before
committing, since no principled predictor exists. And interpretability stops at
what the sheet states — when it is too terse and the model reverts to
pretraining priors, the failure is not visible in the sheet. A footnote also
rebuts the obvious objection that prefix caching already solves this: caching
cuts prefill on a repeated long input, but decode-time attention still runs over
the full context, and hosted-API caches tend to be evicted quickly or billed for
persistence.

## Primary source for this cluster

[aie-059-distillation-with-programmatic-data-curation-cheaper-infer.md](aie-059-distillation-with-programmatic-data-curation-cheaper-infer.md) — no primary digest exists yet for the `distillation-finetuning`
cluster; the nearest neighbour on disk is
`aie-042-speculative-decoding-quantization-and-distillation-tradeof.md`, which
covers parameter-level distillation. This paper is deliberately the opposite
axis: knowledge is distilled into text rather than into weights, which is why it
works on closed proprietary models that cannot be fine-tuned.

## Fidelity check

1. Claim: the token and accuracy figures are 90.0 / 2,036, 91.0 / 42,461, 87.1 /
   2,334, BM25 86.9 / 2,024, cosine 89.1 / 2,294, Set-BSR 89.0 / 2,329. Support:
   the capture reports these values in Table 1, averaged across the eight BBH
   tasks, comparing 8-shot, 150-or-100-shot, the three retrieval baselines, and
   the cheat sheet.
