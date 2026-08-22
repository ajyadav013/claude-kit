---
source: https://www.reddit.com/r/AI_Agents/comments/1ujigq2/a_lot_of_conversation_around_harness_engineering/
author: r/AI_Agents community thread, opened by the user theagenticmind
license-note: ideas absorbed in own words; no text or code reproduced
---

# Practitioners converge on the harness as everything that is not the model

## What it adds beyond the primary

Mostly corroboration, and its value is that the corroboration is unsolicited
and comes from ~25 independent practitioners rather than from one author.
Several answers relay the primary cluster taxonomy second-hand (steering rules
applied before the agent acts versus checks applied after it acts; controls
that are deterministic and cheap versus controls that need a model to judge
meaning; and a difficulty ladder from code quality, to architectural
conformance, to functional correctness, with correctness described as still
unsolved) — which is useful evidence that the taxonomy has actually
propagated, not just been published. Three things here are genuinely
additional. First, a costing argument: multiple commenters claim the harness
now explains more of the outcome than the model choice does, one putting the
model at roughly a third of whether the system works, one reporting a
self-measured ~30% development-velocity gain from harness work alone, and
several arguing that a mid-size or locally-hosted model inside a strong
verification loop reaches frontier-model quality on a narrow domain — with
one commenter preferring local models specifically because provider
availability and token cost are unpredictable. Second, one long practitioner
answer states an autonomy rule the kit does not phrase this way: how far you
let an agent run should be sized to how good your checker is, which makes
autonomy a function of verifier strength rather than of policy alone. Third,
the thread documents that the vocabulary is unsettled — harness, scaffolding,
guardrails, orchestration, and control plane are used for overlapping things,
as are the emerging job titles, and one commenter argues the honest move is to
listen for the job being described rather than the word chosen.

Operational specifics worth keeping, all from the same detailed answer: treat
files in the repository rather than the conversation as the record, kept
append-only and timestamped so nothing is silently rewritten and any point is
recoverable; never let the component that produced a change be the component
that approves it, with cheap deterministic checks running first so a frontier
model is not paid to confirm that a file parses, a separate judging model
next, and a human on the genuine judgment calls; and convert each observed
failure into a standing guard rather than a one-off patch. The same commenter
reports the harness catching a cost regression where a session's first turn
cost roughly ten times the others, traced to a caching problem — a concrete
argument for per-turn cost observability at the harness layer. A skeptical
minority holds that this is a fancy name for tools and scaffolding that
competent teams already built, which is itself a finding: the term is new, the
practice is not.

## Primary source for this cluster

[aie-002-what-is-an-ai-agent-harness.md](aie-002-what-is-an-ai-agent-harness.md)

## Fidelity check

1. Claim: the consensus definition treats the harness as everything in the
   agent that is not the model. Support: the capture shows several
   independent commenters describing the harness as everything around the
   model — context assembly, tool routing, retries, validation, state, and
   the loop that decides what runs next — with one stating flatly that
   anything which is not a model is harness.
