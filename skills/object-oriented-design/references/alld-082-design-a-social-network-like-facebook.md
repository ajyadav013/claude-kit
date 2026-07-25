---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/social-networking-service.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Social network core: user graph, content, and typed notifications behind one service facade

## What it teaches

How to lay out the object model for a feed-based social product at
interview scale. The domain splits into four clusters: the *user* (identity,
profile, friend list, authored posts), *content* (posts holding text and media
references plus their attached likes and comments), *engagement* (comments as
first-class records linking user, post, and body), and *signals* (notifications
as typed events targeted at a user). One service facade owns registration,
login, friendship, posting, feed assembly, and notification fan-out, and the
concurrency approach is again structural — concurrent maps and copy-on-write
lists — rather than explicit lock management. The newsfeed is defined
behaviorally: the union of a user's own posts and their friends' posts in
reverse-chronological order, generated on read.

## Key patterns & decisions

- **User as the graph node.** The user record carries both profile data and the
  adjacency (friend list) plus authored content, making friendship a symmetric
  edge stored on the node and the feed a one-hop graph traversal.
- **Friend requests as a two-step handshake.** Connections require
  send-then-accept/decline rather than instant linking — the request itself is
  a stateful object in the workflow, and its lifecycle events feed
  notifications.
- **Posts aggregate their own engagement.** Likes and comments hang off the
  post record; a comment additionally back-references both its author and its
  post, so engagement can be queried from either direction.
- **Typed notification events.** A notification enum (friend request, request
  accepted, like, comment, mention) turns "tell the user something happened"
  into a closed, extensible vocabulary — the standard shape for event-driven
  UX.
- **Pull-model newsfeed.** The feed is computed at read time by merging the
  user's and friends' posts and sorting newest-first — simple, always
  consistent, no fan-out storage.
- **Copy-on-write for read-heavy shared lists.** Alongside concurrent maps, the
  design uses copy-on-write list structures — the right structural choice when
  reads (feed renders) vastly outnumber writes (new posts).
- **Single facade, singleton lifetime.** All operations route through one
  service object, mirroring the other problems in this series.

## When to apply / trade-offs

- The four-cluster split (identity/graph, content, engagement, signals) is a
  durable starting schema for any app with follows and feeds; the typed
  notification enum in particular transfers directly to real systems.
- Pull-model feeds are correct and cheap at small scale but recompute the merge
  on every read; at scale you graduate to precomputed fan-out-on-write (or a
  hybrid for high-degree nodes) — this design deliberately stops before that.
- Storing the friend list and post list on the user object couples graph and
  content storage; sharding either forces the edges and posts into their own
  stores keyed by user ID.
- Copy-on-write lists penalize every write with a full copy — fine for
  interview scale, pathological for hot posts with thousands of likes.
- The requirements demand privacy controls and per-post visibility, but the
  entity list has no visibility field or ACL object — a gap between the stated
  requirements and the sketched model worth noticing (feed generation would
  need a visibility filter pass).

## Fidelity check

1. *Claim: the feed is the user's own plus friends' posts, newest first.*
   Supported: the capture's requirements state the newsfeed consists of posts
   from friends and the user themself, sorted reverse-chronologically.
2. *Claim: notifications are a closed typed vocabulary.* Supported: the capture
   lists a notification-type enum covering friend request, acceptance, like,
   comment, and mention events.
3. *Claim: concurrency is handled with concurrent maps plus copy-on-write
   lists.* Supported: the capture states shared access is managed through
   ConcurrentHashMap and CopyOnWriteArrayList-style structures rather than
   explicit locking.
