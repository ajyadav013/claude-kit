---
source: https://icml.cc/virtual/2026/poster/65405
author: Minsoo Kim, Arnav Kundu, Han-Byul Kim, Richa Dixit, Minsik Cho (ICML 2026)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Compress the KV cache per topical episode, not per query, to keep memory flat

## What it teaches
Long-running conversational assistants hit a memory wall that has nothing to do
with the model's advertised context length: the Key-Value cache grows linearly
with dialogue history, so a device with a fixed memory budget runs out long
before the context window does. The paper's central observation is that the two
obvious mitigations are each broken in a specific way. Compressing *after* the
whole history has been prefilled still requires materialising the full cache
first, so peak memory is unbounded even though steady-state memory is small.
Evicting based on the *current query* produces a cache whose semantics are
narrowed to that one question, which fails on the next turn when the user asks
something adjacent. EpiCache's answer is to make the compression unit a
*topical episode* rather than a query or the whole transcript — cluster the
history into coherent episodes, build one compressed cache snapshot per
episode, and at query time retrieve only the relevant snapshot. Combined with
block-wise prefill (which bounds peak memory during ingestion) and a
layer-sensitivity-aware split of the memory budget, the method is training-free
and holds accuracy near the uncompressed baseline.

## Key patterns & decisions
- **Peak memory, not steady-state memory, is the binding constraint** — a
  compression scheme that only shrinks the cache after the full context has been
  processed still needs the full cache to exist at some instant. The paper
  explicitly calls out post-hoc eviction as incurring unbounded peak memory.
  Budget the worst moment, not the average.
- **Block-wise prefill bounds ingestion cost** — ingest the conversation in
  blocks and compress as you go, so the cache never has to be fully
  materialised. This is what converts an unbounded peak into a fixed budget.
- **Episodes are a better compression unit than queries** — clustering history
  into topically coherent chunks (chapter-like segments of the conversation)
  and evicting *within* an episode preserves the semantics of a subject area
  rather than of one question, which is what multi-turn dialogue actually needs.
- **Query-dependent eviction is a multi-turn trap** — it looks great on
  single-shot benchmarks and degrades on follow-ups, because the retained cache
  was optimised for a question the user has already moved past. Beware any
  eviction policy tuned on single-turn evals.
- **Retrieval at query time is over episode snapshots, not raw history** — a
  question selects the most relevant precomputed compressed snapshot. Total
  memory stays flat as the conversation grows because you hold one snapshot,
  not N.
- **Layers are not equally compressible** — the budget is distributed unevenly
  across the model's layers, giving more to layers whose accuracy degrades most
  under compression. A uniform per-layer budget leaves accuracy on the table.
- **Training-free is the deployment-relevant property** — the framework is
  applied to an existing model without finetuning, so it is an inference-serving
  change rather than a model change, and can be adopted or reverted per
  deployment.
- **The measured envelope: 4–6x compression at near-full accuracy** — reported
  gains are up to 30% accuracy over prior methods, up to 2.4x lower latency, and
  up to 3.7x lower peak memory, across LongMemEval, Realtalk, and LoCoMo.
- **Benchmark on long-conversation QA, not long-document QA** — the three named
  benchmarks are conversational-memory suites; single-pass long-document evals
  will not surface the multi-turn failure mode this work targets.

## When to apply / trade-offs
This matters when you serve a stateful, long-lived conversational assistant
under a hard memory ceiling — on-device or edge inference, or a shared GPU where
per-session KV footprint determines how many concurrent sessions fit. It is
irrelevant if you run short, stateless request/response calls, or if you consume
a hosted API where the provider owns the cache (you cannot install an eviction
policy inside someone else's serving stack; there your lever is prompt caching
and context curation). The costs are real: you take on an episode-clustering
step over the history, you store per-episode snapshots, you add a
retrieval/selection step in the query path, and you inherit a new failure mode
where the selected episode is the wrong one and the model answers from a cache
that lacks the needed turns. Compression is also lossy by construction — the
4–6x figure is where accuracy stayed near full cache, not a limit that
generalises to every workload, so treat it as a starting point for your own
measurement rather than a setting to copy. If your quality bar cannot tolerate
any recall loss on old turns, buy memory instead.

## Fidelity check
1. Claim: query-dependent eviction fails on multi-turn conversation. Support:
   the capture states that query-dependent eviction narrows the cache semantics
   to a single query, leading to failure cases in multi-turn conversations.
2. Claim: the method clusters history into episodes and evicts per episode.
   Support: the capture describes episodic KV compression that clusters
   conversation history into coherent episodes and performs episode-specific KV
   cache eviction, and the lay summary describes building a compact compressed
   memory snapshot per episode and retrieving only the relevant one at query
   time.
3. Claim: the numbers are up to 30% accuracy, 4–6x compression at near-full
   accuracy, 2.4x latency and 3.7x peak-memory reduction on LongMemEval,
   Realtalk, and LoCoMo. Support: the capture reports exactly these figures and
   these three LongConvQA benchmarks.
