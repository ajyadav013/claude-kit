# Digest: Design YouTube (LLD)

- **Title:** Design Youtube (Low-Level Design series #3)
- **Source:** https://x.com/Harry_The_Nerd/status/2060001018134553006
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** LLD
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Relationship taxonomy: inheritance vs composition vs aggregation vs self-reference
The article's core teaching device is picking the right ownership semantics for each pair of
domain classes before writing any code:

- **Inheritance (is-a):** a channel owner subclasses the ordinary account type, inheriting all
  viewer behavior and adding upload/management capabilities.
- **Composition (part-of, owning):** videos are lifecycle-bound to their creator — deleting the
  channel destroys the videos, because a video has no meaning without its owner.
- **Aggregation (has-a, non-owning):** a creator holds a subscriber list, but those accounts
  live independently; channel deletion must not cascade into subscriber accounts.
- **Self-referencing composite:** a comment holds child comments, giving arbitrarily deep
  reply threads from one recursive class.

When to use: any object-model design where delete-cascade and lifetime coupling matter.
Trade-off: composition gives simple cleanup but hard coupling; aggregation keeps entities
independent but pushes referential-integrity handling elsewhere.

### Lifecycle state as an enum
Video status (processing, public, private, deleted) is modeled as a closed set of constants
rather than loose strings or booleans. When to use: any entity with a small, fixed set of
mutually exclusive lifecycle stages. Trade-off: compile-time safety and exhaustive handling
vs needing a code change to add a stage; the article stops short of a full state machine
(no transition rules are defined, only the states).

### Role extension by subclassing the base account
Elevated roles reuse the base user's fields and behavior through inheritance instead of
duplicating them, and the subclass layers on role-specific state (owned videos, subscriber
tracking). Paired with LSP: any collection typed to the base user can transparently hold
both roles. Trade-off: cheap reuse and substitutability, but roles become fixed at
construction time — a viewer "becoming" a creator is awkward under subclassing (the article
does not address role migration).

### Aggregate-root entity as a data hub
The video class centralizes everything about one piece of content — metadata (title,
duration), an owner reference, and interaction lists (likes, comments). When to use: when
one entity is the natural attachment point for related collections. Trade-off: convenient
single access point vs the risk of the class swelling into a god object as features accrue;
the article leans on SRP to keep behavior out of it.

### Composite pattern for nested comment threads
Each comment carries a list of comments as replies, so one class expresses a tree of
unbounded depth — replies to replies need no new type. When to use: threaded discussions,
menus, org charts, any recursive containment. Trade-off: elegant uniform traversal, but
unbounded recursion needs depth limits and careful rendering/pagination in a real system
(not covered by the article).

### Observer pattern for subscription fan-out
Uploading a video triggers a notify-subscribers call on the creator (the subject), pushing
the event to every subscribed user (the observers). When to use: one-to-many event
propagation where the producer shouldn't know consumer details. Trade-off: decoupled
notification at the object level; the article models it as synchronous in-process fan-out,
which would not survive real YouTube-scale subscriber counts (that's a system-design
concern it doesn't claim to solve).

### Factory pattern for role-aware instantiation
A dedicated factory decides whether to construct a plain user or a creator, so business
logic never contains constructor-selection branching. When to use: multiple concrete types
behind one conceptual "create account" operation. Trade-off: one more indirection layer in
exchange for a single place to change instantiation rules.

### SOLID as a design checklist (SRP, LSP, OCP, ISP)
The article validates the model against four of the five SOLID principles: each class owns
one concern (SRP); the creator subclass is substitutable wherever the base user is expected
(LSP); new variants — a premium account, a live stream — arrive by extension, not by
editing existing classes (OCP); and method sets are split per role instead of one bloated
interface (ISP). Notably, dependency inversion (DIP) is absent from the list — consistent
with a model that has no infrastructure boundary to invert.

## Not absorbed

- Series framing and prerequisite advice (read LLD article #1, practice design questions on
  LeetCode) — interview-prep guidance, not engineering content.
- "That's all, folks" sign-off and engagement footer (views/likes/reply counts) — social
  metadata.
- The "Final code" promise — the heading exists but no code survives in the text capture
  (presumably posted as images), so there is nothing to absorb.
- Beginner-friendliness disclaimers in the overview — audience positioning, not substance.

## Fidelity check

- **Post count in capture:** 1 (a single long-form post; `postCount: 1` in the JSON, no
  `---AUTHOR-POST-BREAK---` separators present).
- **Article outline as authored:**
  1. Overview (Problem Statement)
  2. Architecture and Class Relationships
  3. Core Domain Classes — 1. State Configuration, 2. The User, 3. The Content Creator,
     4. The Video Model, 5. Comments
  4. SOLID Principles Applied
  5. Design Patterns Applied — 1. Observer, 2. Composite, 3. Factory
  6. Key Relationships
  7. Final code
- **Pattern-to-section citations:**
  - Relationship taxonomy → section 2 (Architecture and Class Relationships), reinforced by
    section 6 (Key Relationships).
  - Lifecycle state as an enum → section 3.1 (State Configuration).
  - Role extension by subclassing → sections 3.2 (The User) and 3.3 (The Content Creator),
    plus the LSP entry in section 4.
  - Aggregate-root entity as a data hub → section 3.4 (The Video Model).
  - Composite pattern for nested threads → section 3.5 (Comments) and section 5.2
    (Composite Pattern).
  - Observer pattern for subscription fan-out → section 5.1 (Observer Pattern).
  - Factory pattern for role-aware instantiation → section 5.3 (Factory Pattern).
  - SOLID as a design checklist → section 4 (SOLID Principles Applied).
