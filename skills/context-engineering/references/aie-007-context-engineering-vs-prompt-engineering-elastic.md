---
source: https://www.elastic.co/search-labs/blog/context-engineering-vs-prompt-engineering
author: Tomás Murúa — Elasticsearch Labs (Elastic)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Prompt failures and context failures need different debugging tools

## What it teaches

The piece argues that what used to be one skill ("prompting") is splitting into
two disciplines the way web design split into UI and UX: prompt engineering
governs *how* you phrase a single interaction, context engineering governs
*what* the model can see at inference time. Its most useful contribution is a
dimension-by-dimension contrast table that makes the split diagnostic rather
than philosophical: the two disciplines differ in scope (one query vs.
system-wide information flow), in characteristic failure mode (ambiguity vs.
retrieval problems), in how they treat tools (describing desired output vs.
selecting and sequencing them), and — critically — in how you debug them
(linguistic precision vs. data architecture). It frames context as everything
that enters a stateless function call: instructions, retrieved documents, past
turns and tool results, and output-format directives. It then walks a concrete
agent demo over a 103,063-document book index that reproduces each failure
class in isolation and shows the fix is different in each case.

## Key patterns & decisions

- **Diagnose which discipline owns the failure before fixing anything** — the
  article's central operational move. A bad answer caused by ambiguous wording
  will not be fixed by tuning retrieval, and a bad answer caused by dumping 100
  unfiltered documents will not be fixed by rewording. Ask first: was the
  instruction under-specified, or was the wrong information present?

- **Three context-window failure modes, not one** — too little context pushes
  the model into hallucination because it cannot establish semantic grounding;
  too much overflows attention and flattens relevance across the whole window;
  and distracting or conflicting material actively pulls the answer off. Note
  the second and third get *more* likely as windows grow, not less.

- **"Right altitude" for instructions** — the article borrows Anthropic's
  framing: one failure extreme is hardcoding brittle conditional logic into the
  prompt to pre-anticipate every scenario (fragile, high maintenance), the
  other is vague guidance that assumes shared context the model does not have.
  The target is specific enough to constrain, loose enough to leave judgement.

- **The human-disambiguation test for tool sets** — if a human engineer cannot
  say definitively which of your tools should fire in a given situation, an
  agent will not do better. This converts "bloated overlapping tool set" from a
  vague smell into a checkable review question, and yields the rule: curate the
  minimal viable set, each tool self-contained, error-robust, unambiguous.

- **Tools should be token-efficient by construction** — a tool should return
  only what is needed, not everything it can. This puts context discipline
  inside the tool contract rather than leaving it to post-hoc filtering.

- **Just-in-time context vs. pre-retrieval, with an explicit trade-off** —
  classic RAG front-loads everything potentially relevant before inference;
  the just-in-time style (the article cites Anthropic's Agent Skills) keeps
  lightweight handles — file paths, stored queries, document IDs — and loads at
  runtime via tools. Pre-retrieval is faster but risks overflow; JIT is slower
  but keeps the window focused. The recommended default is hybrid: a small
  baseline retrieved up front plus tool-driven exploration on demand.

- **Context engineering thinks in sequences, prompt engineering in turns** —
  the questions that matter are what earlier turns established, which tool
  outputs must carry forward, and what still needs to be present three steps
  later. Single-turn optimization has no vocabulary for any of that.

- **Same tools, different outcomes — input quality is the variable** — the demo
  ran all three scenarios against the identical agent and tool set. Only the
  prompt specificity and the retrieval focus changed, and that alone separated
  irrelevant results from on-target ones. Tool inventory was never the fix.

- **Concrete-example prompting is a retrieval lever, not just a phrasing
  lever** — naming two exemplar works in the request produced a targeted search
  that pulled a handful of matches out of six figures of documents. Specificity
  in the prompt is what let the retrieval stage stay small.

## When to apply / trade-offs

This framing earns its keep the moment a system stops being single-turn
question-answering and acquires retrieval, tools, or multi-step loops — that is
exactly where the article says context engineering becomes the dominant
challenge. For a thin wrapper over one model call with no external data, the
extra machinery is overhead and prompt-level work is genuinely sufficient. The
costs are real: just-in-time loading adds round-trips and latency versus
pre-fetching, minimal tool sets mean saying no to convenient overlapping tools,
and maintaining the discipline boundary means someone has to own information
architecture rather than only prompt copy. The article is also vendor-adjacent
— the demo runs on Elastic Agent Builder over Elasticsearch — so treat the
product specifics as illustration and the taxonomy as the transferable part.
Do not read it as an argument that prompt engineering is obsolete; its explicit
conclusion is that production teams need both skill sets and, increasingly,
people who understand how the two interact.

## Fidelity check

1. Claim: the two disciplines differ along scope, failure mode, tool handling,
   and debugging approach. Support: the capture contains a comparison table
   with exactly those dimension rows, pairing "single query" against
   "system-wide information flow", ambiguity against retrieval problems, and
   linguistic precision against data architecture.
2. Claim: there are three distinct context-window failure modes. Support: the
   capture enumerates too little information leading to hallucination, too much
   information causing overflow that lowers relevance across the window, and
   distracting or conflicting information confusing the model — and notes
   larger windows raise the odds of the third.
3. Claim: the demo used one index of 103,063 documents and the same tools
   across all three scenarios. Support: the capture gives the index size as
   103,063 books, describes scenarios for an ambiguous prompt, an unfiltered
   retrieve-everything query returning 100 mixed-category books, and a
   preference-specific prompt, then states the agent used the same tools in all
   three cases with input quality determining effectiveness.
