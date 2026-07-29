---
source: https://thomasthelliez.com/blog/how-i-built-an-ai-agent-architecture/
author: Thomas Thelliez
license-note: ideas absorbed in own words; no text or code reproduced
---

# Five to seven role-isolated LLM calls, with deterministic checks gating repair

## What it adds beyond the primary

This is the only article in its cluster, so it stands as its own primary; the
value it adds is a first-person field report of decomposing one generation task
into bounded agent roles. Concrete specifics claude-kit does not currently state:
(a) the *repair* step is scoped to patch only the checks that failed rather than
re-running the whole chain, which the author credits with cutting latency spikes;
(b) roughly half the reliability comes from **non-LLM** validators — schema
conformance, required-section coverage, WCAG-style contrast thresholds, image
availability, and markup-structure checks — and only failures are fed back as a
minimal instruction set; (c) deliberately keeping deterministic work (building
image URLs) outside the model's token budget; (d) an honest negative result — a
separate "architect" agent was tried, found to add latency and tokens without
payoff, and its duties were folded back into two neighbouring roles. The author
also names the trade-off plainly: the pipeline is slower than one prompt, and
that was accepted because output quality ranked first.

## Primary source for this cluster

_No primary digest for this cluster — the designated primary source could not be fetched._
(single-article cluster — this digest is the primary)

## Fidelity check

1. Claim: five to seven LLM calls per generation, five in the standard flow with
   one or two more when repair runs. Support: the capture states a single
   generation usually takes 5 to 7 calls, standard flow 5, plus 1 or 2 with the
   QA repair loop.
