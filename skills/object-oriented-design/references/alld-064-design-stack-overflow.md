---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/stack-overflow.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Entity model for a Q&A community platform

## What it teaches

This problem exercises entity-relationship modeling for a content platform:
users produce several kinds of content (questions, answers, comments), content
accrues social signals (votes), and those signals feed back into a per-user
reputation score. The instructive part is how many small, single-purpose
entities emerge — rather than one "post" blob, the model gives questions,
answers, comments, tags, and votes each their own class, with the
relationships (an answer belongs to a question; a comment attaches to either a
question or an answer; a tag links to many questions) carrying most of the
design's meaning.

The second lesson is the facade at the top: one coordinating class owns the
whole system's use cases — registering users, posting each content type,
voting, searching, and filtered retrieval — so callers interact with a small
verb-oriented surface while the entity graph underneath stays normalized.

## Key patterns & decisions

- Fine-grained entity decomposition: question, answer, comment, tag, vote, and
  user are separate classes instead of a generic post type, so each carries
  only the fields it needs.
- Vote reified as an entity: votes are modeled as objects tied to a question
  or answer rather than as a bare integer counter, which preserves who voted
  and enables dedup/undo semantics.
- Dual-target commenting and voting: both questions and answers accept
  comments and votes, hinting at a shared "commentable/votable" abstraction
  across the two content types.
- Tags as a many-to-many join: a tag is its own identity-bearing entity, which
  is what makes tag-based retrieval a first-class query rather than a string
  match on content.
- Reputation as derived state: a user's reputation is computed from their
  activity and how the community rates their contributions — an event-driven
  aggregate, not an independently editable field.
- Multi-axis search: the system must resolve queries by keyword, by tag, and
  by author, pushing the design toward maintained indexes/lookups per axis.
- Facade/aggregate coordinator: a single system class exposes all use cases
  (create, post, vote, search, retrieve-by-tag/user) and hides the entity
  wiring from callers.
- Concurrency and consistency named up front: concurrent access with data
  consistency is an explicit requirement, meaning vote counts and reputation
  updates must be treated as contended shared state.

## When to apply / trade-offs

- Use vote-as-entity whenever you need idempotence ("one vote per user") or
  reversibility; the cost is a join/aggregation to display a count, usually
  mitigated with a cached tally.
- Derived reputation keeps the score trustworthy but creates ordering and
  race concerns — recomputing versus incrementally applying deltas is the real
  design decision the requirement smuggles in.
- The single facade is fine at interview scale but becomes a god object in a
  real service; the same surface would be split across services or modules
  with the entity relationships preserved.
- Duplicating comment/vote support on two content types invites either an
  interface both implement or a shared base — choose based on whether the two
  types will keep diverging.

## Fidelity check

1. Claim: votes are modeled as their own objects, not counters. Support: the
   capture lists a dedicated vote class associated with a question or answer,
   separate from the question/answer classes themselves.
2. Claim: reputation is driven by activity and contribution quality rather
   than being a free-standing attribute. Support: the capture's requirements
   state the system assigns reputation based on user activity and the quality
   of contributions.
3. Claim: one coordinating class fronts every use case. Support: the capture
   describes a main system class providing methods for user creation, posting
   questions/answers/comments, voting, searching, and retrieving questions by
   tag or user.
