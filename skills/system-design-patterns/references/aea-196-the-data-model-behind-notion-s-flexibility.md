---
source: https://www.notion.com/blog/data-model-behind-notion
author: Notion
license-note: ideas absorbed in own words; no text or code reproduced
---

# A single atomic record type ("block") as the whole product's data model

## What it teaches

Notion models every visible piece of content — paragraphs, list items, images,
database rows, even entire pages — as one record type: the block. A block carries
a UUID, a type tag, a bag of properties, an ordered list of child-block IDs, and
a single parent pointer. The article walks through how this one abstraction
supports rendering, editing, permissions, offline-tolerant persistence, and
real-time collaboration.

## Key patterns & decisions

- **Universal atomic unit.** One record shape for all content kinds, discriminated
  by a `type` field. New features become new block types rather than new tables
  or new persistence paths.
- **Type/property decoupling.** Converting a block to another type rewrites only
  the type tag; properties the new type does not understand are kept, not
  dropped. Round-tripping a checked to-do through other types and back restores
  the checkmark — the model deliberately preserves user intent that the current
  renderer ignores.
- **Dual pointer system with distinct jobs.** Downward pointers (each block's
  ordered child-ID array) define the render tree and sibling order; a separate
  upward parent pointer exists solely for the permission system. The two mirror
  each other but are stored independently because permission checks need a fast,
  unambiguous walk to the root — a child can historically appear in more than
  one content array, and scanning every content array to find ancestors would be
  prohibitively slow on clients.
- **Structure over styling.** Indentation is not a visual property; it reparents
  the block into the preceding sibling's child list. The document's appearance
  is a direct projection of the tree.
- **Optimistic local apply + durable outbox.** Edits become operations, batched
  into transactions. The client applies them to in-memory state (and a local
  LRU record cache over SQLite/IndexedDB) immediately, while a persisted
  transaction queue drains to the server — surviving crashes and offline gaps
  until each transaction is acknowledged or rejected.
- **Server-side before/after validation.** The save endpoint loads the affected
  records, clones them, applies the operations to the clone, then compares the
  two states to check permissions and coherency before committing the batch
  atomically.
- **Version-notify, then pull.** Collaborators hold a WebSocket subscription per
  rendered record. The realtime service pushes only new version numbers; a
  client that sees a version ahead of its cache issues a sync request for the
  stale records. Notifications are cheap; payloads travel over the normal API.
- **Recursive chunked page load with layered caches.** Opening a page tries
  memory, then the local record cache, then a server call that walks the content
  tree from the page root and returns the blocks plus every dependent record
  needed to render them.

## When to apply / trade-offs

- Fits products where users compose arbitrary structures from small pieces
  (editors, whiteboards, low-code tools). Overkill for fixed-schema CRUD apps.
- Property preservation across type changes costs storage and demands renderers
  that tolerate unknown fields, but it is what makes destructive-feeling
  operations reversible in collaborative settings.
- Separating the permission path (parent pointer) from the render path (content
  arrays) duplicates relationship data and admits edge-case divergence the team
  acknowledges having to clean up — accepted to keep permission checks
  unambiguous and fast.
- Version-push/state-pull adds a round trip versus pushing full deltas, but
  keeps the realtime fanout service tiny and stateless about content.
- The recursive tree crawl on cold page loads can mean many database trips, so
  the design leans heavily on caching at every layer.

## Fidelity check

1. Claim: transforming a block's type keeps properties the new type ignores.
   Support: the capture demonstrates a checked to-do turned into heading and
   callout types and back, with the checked state intact at the end.
2. Claim: the parent pointer exists only for permissions, not rendering.
   Support: the capture states the parent attribute serves the permission
   system, and gives two reasons content arrays cannot: multi-referenced blocks
   make inheritance ambiguous, and ancestor lookup via content arrays is
   inefficient.
3. Claim: clients persist unacknowledged transactions locally before the server
   confirms them. Support: the capture describes a transaction queue backed by
   IndexedDB or SQLite that holds transactions until the server persists or
   rejects them.
