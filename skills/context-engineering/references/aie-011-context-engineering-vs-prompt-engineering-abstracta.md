---
source: https://abstracta.us/blog/ai/context-engineering-vs-prompt-engineering
author: Sebastián Lorenzo — Abstracta
license-note: ideas absorbed in own words; no text or code reproduced
---

# Memory is not storage — it needs write, read, and maintenance policies

## What it adds beyond the primary

Most of this piece restates the cluster consensus (prompt engineering optimizes
one turn; context engineering designs the whole informational environment;
prompting is a sub-layer of context assembly) via a dimension table covering
unit of design, scope, state, knowledge, tool usage, scalability, risk control,
and enterprise readiness. Its one genuinely additive contribution is the claim
that saving information is not the same as having memory: memory only works
under three explicit policies. **Write policy** — store only stable, reusable
facts (preferences, domain definitions, confirmed decisions), never transient
state or unnecessary sensitive data, and write at task end or on a strong
signal of future usefulness. **Read policy** — retrieve by trigger (topic,
entity, objective) or by score combining similarity, recency, and priority,
then inject compressed rather than dumping everything. **Maintenance** —
active forgetting, contradiction resolution that prefers the most recent
validated version, priority ordering, and permission scoping that separates
personal, project, and public memory. It also treats prompt-injection defence
as a retrieval-stage concern: retrieved documents are data, never instructions.

## Primary source for this cluster

[aie-007-context-engineering-vs-prompt-engineering-elastic.md](aie-007-context-engineering-vs-prompt-engineering-elastic.md)

## Fidelity check

1. Claim: the article splits memory governance into write, read, and
   maintenance policies. Support: the capture shows three headed subsections
   under Context Management labelled write policy, read policy, and
   maintenance, prefaced by the statement that merely saving things is not
   enough and an explicit policy is required.
