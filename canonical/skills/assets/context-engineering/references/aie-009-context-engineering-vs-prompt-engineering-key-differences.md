---
source: https://www.glean.com/perspectives/context-engineering-vs-prompt-engineering-key-differences-explained
author: Glean Technologies
license-note: ideas absorbed in own words; no text or code reproduced
---

# Long context degrades accuracy on its own, not just by adding distraction

## What it adds beyond the primary

Mostly corroboration of the standard framing, but with three quantified hooks the
primary does not supply. First, a 2025 study cited here reports a 24.2% accuracy
drop when the needed evidence sits inside a longer window even after every
irrelevant token is masked out; that isolates *length* from *distraction*: the
model was made to attend only to the question and the supporting evidence, and
accuracy still fell, so trimming noise alone will not buy back the loss — you
also have to keep the window short.
Second, it cites a randomized controlled trial in which developers were 19%
slower on complex tasks with AI assistance while believing they had been sped up
by 20%, which is a direct argument for measuring context changes rather than
trusting practitioner impressions. Third, it cites an analysis of 32 datasets
finding 91% of machine-learning models degrade in performance over time even
under stable training distributions, which reframes context configuration as
something requiring continuous re-evaluation rather than a one-time tuning pass.
The article also draws an ownership line the kit never states explicitly —
prompt engineering is user-facing and transient, context engineering is
developer-facing system infrastructure — and it flags permission-aware context
in shared enterprise environments as a first-class design constraint, noting an
F5 figure that only 2% of organizations are judged highly ready to scale AI
securely against 77% at moderate readiness overall.

## Primary source for this cluster

[aie-007-context-engineering-vs-prompt-engineering-elastic.md](aie-007-context-engineering-vs-prompt-engineering-elastic.md)

## Fidelity check

1. Claim: a 2025 study found a 24.2% accuracy drop when relevant information is
   embedded in longer contexts even with irrelevant tokens masked and attention
   restricted to evidence and question. Support: the capture states exactly this
   in its section on memory-management complexity, including the masking and
   attention conditions.
