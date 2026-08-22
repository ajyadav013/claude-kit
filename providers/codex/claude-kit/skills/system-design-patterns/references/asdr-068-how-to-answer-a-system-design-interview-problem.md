---
source: https://algomaster.io/learn/system-design-interviews/answering-framework
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# A phased default flow for reasoning through open-ended system design problems

## What it teaches

Design interviews (and by extension any ambiguous architecture task) reward a
repeatable sequence: pin down scope, size the load, sketch interfaces, draw a
minimal architecture, model the data, then go deep on the one or two genuinely
hard subsystems. The chapter frames this as a default path to adapt, not a
script to recite — the interviewer's redirections outrank the checklist. The
seven phases come with rough time budgets for 45- and 60-minute sessions
(requirements ~5-7 min, deep dives the largest block at 12-18 min), and the
core discipline is that each phase's output should visibly feed the next:
requirements drive the estimates, estimates justify the components, the
component diagram exposes the data model, and the data model surfaces the
bottlenecks that deserve deep dives.

## Key patterns & decisions

- **Scope-before-solution clarification**: propose a concrete feature scope and let the counterpart trim it, rather than either freezing on ambiguity or regurgitating a memorized architecture.
- **Stated-assumption fallback**: when a stakeholder won't give a number, pick a plausible one, say it out loud, and mark it as revisable — never design on silent assumptions.
- **Estimation as design pressure**: order-of-magnitude math (aggressive rounding to powers of ten) exists only to trigger decisions — heavy reads imply caching/replicas, heavy writes imply partitioning/async ingestion, big data implies distributed storage, big payloads imply CDN/compression.
- **Incremental architecture evolution**: start from the simplest single-server design and add each component (load balancer, cache, queue, CDN, shards) only when a named pressure demands it, narrating the reason.
- **Data-flow walkthroughs**: validate a boxes-and-arrows diagram by tracing one concrete use case end to end; the trace is what reveals missing pieces like an async fan-out queue.
- **Access-pattern-first data modeling**: pick SQL vs NoSQL per store by its role (source of truth vs cache vs derived view), design NoSQL schemas around queries not entities, and denormalize deliberately with the consistency cost stated.
- **Structured deep-dive protocol**: state the problem, compare two or three realistic approaches, weigh trade-offs, then commit to a recommendation anchored in the stated requirements (e.g. hybrid push/pull fan-out chosen because of a 200ms feed latency target).
- **Time-boxed checkpoints**: internal milestones ("architecture drawn by minute 15-ish") prevent one phase from starving the highest-signal phase, the deep dive.

## When to apply / trade-offs

- Useful beyond interviews: the same flow structures any design doc or spike where requirements arrive vague. In claude-kit terms it maps cleanly onto spec-driven planning phases.
- The framework's own warning applies: over-clarifying burns the budget just as badly as under-clarifying; after a handful of questions, assume and move.
- Estimation is explicitly optional — skip or compress it when precision won't change any decision.
- The hybrid fan-out example encodes a general trade-off shape: precompute for the common case, compute-on-read for the pathological case (celebrity accounts), and make the threshold adaptive rather than a magic constant.

## Fidelity check

1. Claim: deep dives get the largest time allocation. Support: the capture's phase tables give deep dives 12-18 minutes generally, 15-16 in the 45-minute layout and 18-20 in the 60-minute layout — more than any other phase.
2. Claim: estimates are only worth doing when they alter the design. Support: the chapter says the estimation phase is not arithmetic for its own sake and lists explicit mappings from high read QPS, high write QPS, large storage, and high bandwidth to specific architectural responses.
3. Claim: the recommended fan-out answer is a hybrid keyed on account size. Support: the worked deep dive compares push (write amplification for huge follower counts), pull (slow reads), and lands on pushing for ordinary users while merging high-follower authors' posts at read time, with the cutoff based on follower count, posting rate, and worker capacity.
