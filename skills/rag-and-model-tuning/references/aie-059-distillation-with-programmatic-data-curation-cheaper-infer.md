---
source: https://www.tensorzero.com/blog/distillation-programmatic-data-curation-smarter-llms-5-30x-cheaper-inference/
author: Andrew Jesson, Gabriel Bianconi, Aaron Hill, Viraj Mehta (TensorZero)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Cloning only a teacher's successful trajectories cuts cost per success 5-30x

## What it teaches
The expensive-model-versus-cheap-model tradeoff is not fixed: you can buy
most of a frontier model's task performance at a small model's price by
running the frontier model in production first, keeping only the episodes
that provably succeeded, and supervised-fine-tuning a small model on those
transcripts. The authors call this curated behavior cloning and benchmark it
across four task shapes — entity extraction (CoNLL++ NER), multi-turn text
navigation (BabyAI GoTo), a two-policy agentic RAG loop (Multi-Hop), and
multi-turn tool-using customer service (tau-bench retail and airline) — with
GPT-4.1 as the teacher and Gemini 2.0 Flash/Flash-Lite, GPT-4.1 mini/nano,
GPT-4o mini and Qwen3-8B as students. The headline metric is cost per
success (cost per task divided by success rate), and the reduction factors
range from roughly 1.8x to 31x depending on task and student. Latency drops
too (2-4x), the training sets are startlingly small (410-671 successful
conversations), and the one-time fine-tuning bill was $2.30-$32. The
important operational lesson is that the curation filter — not the
fine-tuning — is what does most of the work, and that everything hinges on
having a programmatic success signal you already log.

## Key patterns & decisions
- **Curate on outcome, then clone** — Train only on trajectories that a
  success metric marked as passing, rather than on every logged call. The
  ablation comparing curated against uncurated training sets shows curated
  consistently ahead on agentic RAG for the GPT students, and still ahead
  on tool use, most visibly on the repeat-reliability metric.
- **Score by cost per success, not cost per token** — Dividing cost per task
  by success rate is the metric that makes the comparison honest: a cheap
  model that fails half the time is not cheap. Under that metric fine-tuned
  Gemini 2.0 Flash-Lite reaches 31.0x on NER, 29.4x on BabyAI, 23.1x on
  Multi-Hop, 15.2x on tau-bench retail and 10.4x on airline.
- **Measure reliability separately from success** — The evaluation reports
  pass^1 (one conversation succeeds) alongside pass^5 (five repeats all
  succeed). A model can hold its single-shot success rate while losing
  consistency, and only the k=5 view exposes that.
- **Distil per policy in a multi-agent loop** — The Multi-Hop setup has two
  distinct roles (generate the next search query; extract notes and titles
  from results). They fine-tuned a separate small model per role, using only
  successful whole-episode demonstrations and no per-role reward signal, and
  several students still beat the teacher's success rate.
- **Prefer a one-time training cost to a recurring inference-time one** —
  Best-of-n sampling, chain-of-thought and dynamic in-context learning all
  multiply every request's cost. Fine-tuning front-loads the spend once; at
  $2.30-$32 for these tasks it amortises within hundreds of conversations.
- **Expect a performance floor on hard agentic tasks** — On tau-bench retail
  the students did not match GPT-4.1; they recovered about 90% of its
  accuracy at roughly 5x lower cost. That is a routing decision, not a
  failure: decide what accuracy delta you can absorb.
- **Out-of-distribution transfer is not guaranteed** — Models fine-tuned
  purely on retail and then run on the airline domain split: Gemini 2.0
  Flash and GPT-4.1 nano improved slightly over their zero-shot selves,
  while GPT-4.1 mini, GPT-4o mini and Flash-Lite regressed. Latency gains
  transferred; quality gains did not.
- **Keep the escape hatch and ramp traffic** — The recommended deployment is
  a router: the fine-tuned small model handles the bulk of traffic, hard
  cases escalate to the large model, and traffic shifts gradually while
  quality metrics are watched. Cross-provider results (OpenAI, Google,
  Qwen via Unsloth) are pitched as reducing lock-in.
- **Budget for drift surveillance** — Because the student learned one input
  distribution, ongoing evaluation is treated as mandatory rather than
  optional; the model degrades silently as inputs evolve.

## When to apply / trade-offs
Reach for this when the task is narrow, repeated at volume, and has a
success criterion you can compute — schema-conformant extraction, a
constrained tool-calling flow, a retrieval loop with checkable ground truth.
It presupposes that you already run the expensive model in production and
log complete request/response episodes with an outcome label, so the real
prerequisite is observability plumbing, not GPUs. The costs are a data
collection phase at frontier prices, a per-provider fine-tuning pipeline to
maintain, a second model version to evaluate and roll out, and permanent
drift monitoring. Skip it for open-ended or low-volume work where the
frontier model's generality is the point, for tasks whose success you can
only judge by expensive human review, and for anything where a 10% accuracy
shortfall is unacceptable and no escalation path exists. Also treat any
adjacent-domain reuse as an experiment: the airline results show a student
can quietly get worse off-distribution.

## Fidelity check
1. Claim: cost savings of 31.0x, 29.4x, 23.1x, 15.2x and 10.4x for
   fine-tuned Gemini 2.0 Flash-Lite. Support: the capture shows a table of
   cost-savings factors relative to GPT-4.1 listing exactly those values
   for that model across NER, BabyAI GoTo, Multi-Hop, tau-bench retail and
   tau-bench airline, defined as reduction in cost per success.
2. Claim: training sets were only a few hundred successful conversations.
   Support: the capture states 446 successful GPT-4.1 conversations for
   BabyAI (356 train / 90 validation), 671 for Multi-Hop (536 / 135) and
   410 for tau-bench retail (328 / 82).
3. Claim: curation itself contributes measurable gains. Support: the capture
   reports an ablation comparing curated (successful-only) against uncurated
   (all demonstrations) training sets, finding curated ahead consistently on
   agentic RAG for GPT models and ahead on agentic tool use, particularly at
   k=5 reliability for GPT-4.1 mini and nano.
