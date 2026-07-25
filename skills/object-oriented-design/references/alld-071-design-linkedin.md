---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/linkedin.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for a professional-networking platform (LinkedIn-style)

## What it teaches

This interview problem is an exercise in decomposing a large product surface
(profiles, a social graph, messaging, job listings, search, notifications)
into a coherent set of domain entities, then hanging every use case off a
single service facade. The lesson is less about any one feature and more
about how to keep a many-featured system navigable: rich value objects for
the data, one orchestrating service for the behavior, and an enum-driven
event/notification vocabulary tying features together.

## Key patterns & decisions

- **Composition over god-objects for the profile.** A member's identity is
  split into a core account entity and a separate profile aggregate, which
  itself composes small value objects for work history entries, education
  entries, and individual skills. Editing profile data never touches
  credentials or graph state.
- **Connections modeled as first-class objects, not bare ID pairs.** A link
  between two members carries its own metadata (notably when it was formed),
  which leaves room for a request/accept lifecycle rather than an instant
  symmetric edge.
- **Singleton service facade.** One central service object owns every
  workflow — registration, login, profile edits, connection requests, job
  posting, search, messaging, notification fan-out — and is instantiated
  exactly once. All entities stay mostly data; behavior concentrates in the
  facade.
- **Typed notification taxonomy.** Notifications are their own entity with a
  closed enum of kinds (new connection request, new message, new job
  posting), so downstream consumers can switch on type instead of parsing
  content.
- **Mailbox as two directional collections.** Each member holds both an
  inbox and a sent-messages collection; a message records sender, receiver,
  body, and timestamp, making conversation reconstruction a pure query.
- **Concurrency via concurrent collections rather than explicit locking.**
  Shared registries (members, jobs, topics of interest) sit in
  concurrent-map / copy-on-write structures so the facade's methods can be
  called from many threads without a global lock.

## When to apply / trade-offs

- Apply the entity-decomposition style whenever a feature request bundles
  several loosely related capabilities: give each capability its own small
  aggregate, then decide deliberately where orchestration lives.
- The single service facade is fine at interview/prototype scale but becomes
  a change-magnet in production; the natural evolution is one service per
  bounded context (graph, messaging, jobs, search) with the facade surviving
  only as an API gateway.
- Singleton-plus-concurrent-collections gives easy thread safety for
  independent map operations, but offers no atomicity across entities (e.g.
  accept-connection touching two users), which is exactly where real systems
  need transactions.
- Storing inbox and sent lists on the user object couples message retention
  to user lifetime; a standalone message store scales and archives better.

## Fidelity check

1. *Claim:* the design centralizes all workflows in one singleton service.
   *Support:* the capture describes a main service class that follows the
   Singleton pattern and exposes registration, login, profile updates,
   connections, job posting, search, messaging, and notification methods.
2. *Claim:* profile content is decomposed into small component objects.
   *Support:* the capture lists separate classes for experience, education,
   and skill entries composed under a profile object that also holds
   picture, headline, and summary fields.
3. *Claim:* thread safety comes from concurrent data structures rather than
   coarse locks. *Support:* the capture states that multi-threading is
   handled with structures like concurrent hash maps and copy-on-write
   lists to protect shared state under concurrent access.
