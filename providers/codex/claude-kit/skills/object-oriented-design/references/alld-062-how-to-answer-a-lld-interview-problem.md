---
source: https://blog.algomaster.io/p/how-to-answer-a-lld-interview-problem
author: ashishps1 (AlgoMaster newsletter)
license-note: ideas absorbed in own words; no text or code reproduced
---

# A five-step method for turning a fuzzy design prompt into an object model

## What it teaches

A repeatable procedure for low-level design (object-oriented design) problems,
demonstrated end-to-end on "design a Q&A site like Stack Overflow." The
method's spine: (1) interrogate the requirements before designing anything,
(2) extract the core entities, (3) design classes in three passes —
relationships, then behavioral contracts, then a single system facade —
(4) implement under good coding discipline with concurrency addressed
explicitly, and (5) sweep for error cases and abusive inputs. The author is
candid that interview time rarely allows all five steps in full, so the
standing meta-move is to keep checking scope with the interviewer.

The worked example shows each step producing concrete artifacts. Requirements
questioning narrows an open prompt to five capabilities (posting Q/A/comments,
voting, tagging, keyword/tag/profile search, and activity-driven reputation).
Entity extraction is framed as noun-mining the problem statement — the nouns
become classes. Relationship mapping captures cardinalities and lifetimes: a
user authors many questions/answers/comments; a question owns many answers,
comments, tags, and votes; comments and tags exist only inside their parent
(composition). Shared capabilities are factored into small behavioral
interfaces — one for "things that accept comments" and one for "things that
can be voted on" — because both questions and answers need both behaviors.
Finally a coordinator class fronts the whole system with the full use-case
API (create user, ask, answer, comment, vote, accept, search), so outside
callers never manipulate the domain objects directly.

## Key patterns & decisions

- **Requirements interrogation before design** — open with scoping questions
  (core features, priorities, user actions, constraints, concurrency
  expectations, error-handling expectations) and lock an explicit feature
  list before drawing anything.
- **Nouns-to-entities extraction** — treat the nouns of the agreed problem
  statement as candidate classes and the verbs as candidate methods.
- **Relationship/cardinality mapping with composition awareness** — decide
  which associations are many-to-one and which are ownership (comments and
  tags live and die with their parent post); a UML sketch is optional and
  worth confirming with the interviewer.
- **Capability interfaces for cross-cutting behaviors** — when two entities
  share a behavior (commentable, votable), define a small contract each
  implements rather than duplicating or inheriting awkwardly.
- **Facade/coordinator entry point** — one central class exposes the system's
  use cases as its API and mediates all object creation, retrieval, and
  interaction, keeping the domain model closed to direct outside manipulation.
- **Concurrency as a named checklist item** — ask whether it is in scope; if
  so, reach for synchronization on shared mutations (reputation updates),
  atomic counters (vote tallies), thread-safe collections (comment storage),
  and immutability where possible.
- **Adversarial edge-case sweep** — close by enumerating rule-violating
  inputs: self-voting, duplicate votes on the same post, empty title/content,
  and whether reputation may go negative.
- **Scope negotiation throughout** — implement only the methods the
  interviewer cares about; a separate demo/driver class is the place to show
  the system working.

## When to apply / trade-offs

Directly applicable to any LLD/OOD interview, but the deeper transfer is to
real feature design: the same sequence (clarify → entities → relationships →
contracts → facade → concurrency → edge cases) is a sound planning skeleton
for a new module. Trade-offs surface in the comments: a reader suggests that
the single coordinator class should be split into per-domain services (user,
question, voting, search) for modularity — a fair critique that the facade
pattern at interview scale under-decomposes at production scale. The article
also concedes UML is optional and full implementation is usually impossible
in the time given, so prioritizing which methods to write is itself part of
the evaluated skill.

## Fidelity check

1. Claim: the method factors shared behaviors into commentable/votable
   contracts because two entity types need both. Support: the capture defines
   a comments contract (add/list comments) and a voting contract
   (register vote/read tally) explicitly because both questions and answers
   support comments and votes.
2. Claim: concurrency handling is tied to specific mechanisms per subsystem.
   Support: the capture recommends atomic operations for vote counts,
   thread-safe structures for comment storage, and synchronized updates for
   user reputation, plus immutability as a general de-risking tool.
3. Claim: the design closes with named edge cases including self-voting and
   negative reputation. Support: the capture's exception-handling step lists
   voting on one's own post, repeat voting on the same content, empty
   question title/content, and whether reputation can drop below zero.
