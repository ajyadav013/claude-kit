---
source: https://arxiv.org/html/2412.14964v2
author: Kujanpää, Marttinen, Valpola & Ilin (Aalto University / FCAI / System 2 AI)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Self-distillation beats imitating a bigger model for knowledge injection

## What it teaches
There are two mainstream ways to give an LLM knowledge it never saw in
pre-training: put the documents in the prompt at query time (RAG) or bake
them into weights (fine-tuning). Fine-tuning has historically lost to RAG
on factual recall. This paper argues the loss is an artefact of the loss
function, not of fine-tuning itself. Instead of training the student on
hard one-hot answer tokens produced by a stronger expert, run the *same*
model twice — once with the source document in its prompt (teacher) and
once without (student, a LoRA adapter over identical base weights) — and
minimise the KL divergence between their token distributions over the
answer. The document's information is thereby transferred into the
adapter. Because teacher and student are the same network, there is no
answering-style or capability mismatch to launder; the gradient is spent
on facts. Across Llama-3-8B, Qwen2.5-14B and Qwen2.5-3B this beat
supervised fine-tuning everywhere, matched or beat closed-book RAG on
Squadshifts, and improved RAG further when stacked with it.

## Key patterns & decisions
- **Soft targets beat hard targets for knowledge injection** — cross-entropy
  on one-hot tokens forces all probability mass onto one continuation, which
  perturbs a distribution that was often already correct and amplifies
  catastrophic forgetting. KL against the teacher's full distribution leaves
  untouched anything the document does not change.
- **Self-distillation beats distilling from a larger expert** — for
  Llama-3-8B, expert=teacher=8B outscored using a 70B Llama or 72B Qwen as
  either expert or teacher. The authors read this as style mismatch swamping
  the stronger model's advantage under parameter-efficient tuning. The one
  exception was the 3B model, too weak to author good training questions,
  where a larger *expert* (data generator) helped.
- **Two temperatures, both above 1** — questions and answers are sampled at
  τ=1.5 for coverage and diversity; distillation itself runs at T>1 so the
  student also learns which tokens the teacher is actively avoiding. Lowering
  either degrades results. SFT wants the opposite (answers at 0.25), because
  it treats sampled text as ground truth.
- **Noisy synthetic answers are tolerable here** — the generated answer is an
  *input* to both teacher and student, not a target. The teacher's logits stay
  well-defined at every position, so the student learns to recover from a
  suboptimal prefix — the DAgger intuition applied to token streams.
- **Data efficiency is the headline operational win** — matching the accuracy
  PD reached with 20 training questions per test question required roughly an
  order of magnitude more data for SFT, and SFT never reached PD's asymptote
  in these runs. PD also won at every LoRA rank tested and was faster in
  wall-clock terms despite needing a second forward pass.
- **The extra forward pass is avoidable** — one network serves both roles by
  toggling the LoRA adapter, so memory matches SFT-with-LoRA. Teacher logits
  can be cached at answer-generation time, or on epoch one of multi-epoch
  training, removing the compute delta entirely.
- **Forgetting is handled by a second KL term, not by hoping** — adding a KL
  penalty on unrelated instruction/response pairs (they used Tülu 3) keeps the
  student near its original distribution on general tasks. On MMLU-Pro this
  lifted the 6-subject mean from 34.0 to 37.2 at a cost of roughly one point
  on the injected-knowledge task.
- **Weights and retrieval compose rather than compete** — PD+RAG beat plain
  RAG on most subsets, and on multi-hop HotpotQA the combination was the best
  configuration, suggesting internalised facts help the model reason over
  retrieved ones rather than duplicating them.
- **Evaluation was triangulated** — LLM-as-judge with a reason-then-grade
  two-step prompt, re-graded with a different-family model, cross-checked with
  substring matching, plus a manual sample that put clear grading errors near
  2%. Base-model scores were reported first to prove the questions probed
  genuinely unknown facts.

## When to apply / trade-offs
This matters when a system must answer from a stable, largely unstructured
private corpus — internal wikis, product docs, support history — and the
operational cost of RAG (a vector store to maintain, retrieval failures,
long prompts on every single request) is what actually hurts. It needs
open weights and logit access, so it is unavailable behind a closed
inference API; it needs a GPU budget for a training run per corpus
version; and freshly changed facts still argue for retrieval, since
re-distilling is slower than re-indexing. Absolute accuracy was also
model-size-bound: the 3B student trailed the 8B and 14B students on every
subset. The honest default for most product teams remains RAG, with
distillation as an upgrade when retrieval quality has plateaued, when the
prompt-length bill dominates, or when you want the model to *reason over*
domain facts rather than quote them — and even then the paper's own best
numbers came from doing both.

## Fidelity check
1. Claim: the student is the same network as the teacher plus a LoRA adapter
   initialised to zero, so both are identical when training starts. Support:
   the capture states the student is the teacher's parameters plus a LoRA
   delta initialised to zero, and that implementation toggles the adapter to
   switch roles without extra memory versus SFT with LoRA.
2. Claim: self-distillation outperformed using a 70B/72B expert or teacher for
   the 8B and 14B base models, with the 3B model as the exception. Support:
   Table 3 in the capture shows PD 8B/8B at 86.1 / 94.4 / 93.6 on Amazon /
   New Wiki / NYT versus 84.0 / 93.0 / 92.3 for PD 70B/70B, and the text
   attributes the gap to answering-style mismatch while noting Qwen2.5-3B
   benefits from a larger expert.
3. Claim: PD is roughly an order of magnitude more data-efficient than SFT.
   Support: the ablation section states that matching PD trained with 20
   training questions required SFT to use an order of magnitude more training
   data, and that SFT did not reach PD's asymptotic performance.
