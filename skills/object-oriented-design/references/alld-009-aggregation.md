---
source: https://algomaster.io/learn/lld/aggregation
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Aggregation: whole-part grouping without lifecycle ownership

## What it teaches
Aggregation is a tightened form of association: there is now a clear container ("whole")
and contained ("part") hierarchy, but the container does not own its parts' lifecycles.
Parts are created elsewhere, can be shared by several containers at once, and outlive any
container that references them. UML marks this with a hollow diamond on the whole's side.
The chapter's litmus test: if a class groups other objects purely for logical organization
— never constructing or destroying them — that's aggregation; the moment the container
manufactures and disposes of its members internally, the relationship has drifted toward
composition-style coupling. A music-library domain (library, users, playlists, songs)
shows aggregation stacked two levels deep.

## Key patterns & decisions
- **Whole-part with independent lifecycles**: a department groups professors, but
  dissolving the department leaves the professors intact and reassignable — the defining
  property separating aggregation from composition.
- **Parts are shareable across wholes**: the same song object sits in multiple playlists;
  the same professor can belong to several departments. One metadata update is visible
  everywhere because every container references the same instance.
- **The container never constructs its parts**: parts arrive from outside. A team that
  internally creates and destroys its developers has silently become composition-like and
  tightly coupled.
- **Inject the parts (constructor/setter DI) as the strongest form**: the chapter's
  bad-good-great ladder ends with dependencies passed in via constructor or setter, which
  maximizes modularity and lets tests substitute mock parts.
- **Authoritative collection + lightweight views**: the library holds the master song
  set; playlists are just bags of references over it. Deleting a playlist deletes only
  the grouping, never the songs.
- **Aggregation composes hierarchically**: users aggregate playlists, playlists aggregate
  songs — at every level the parts survive deletion of the whole above them.
- **UML hollow diamond on the whole side** signals loose containment, versus the filled
  diamond of composition and the plain line of ordinary association.

## When to apply / trade-offs
- Choose aggregation when objects need logical grouping but must remain reusable in other
  contexts — teams of developers, playlists of songs, departments of staff.
- The loose coupling means either side can evolve independently, but it also means the
  container cannot assume exclusive access: a shared part mutated through one container
  changes for all of them, which is sometimes the feature (single source of truth) and
  sometimes a surprise.
- Watch for the composition drift smell: factory methods on the container that mint its
  own members undermine testability and reuse; prefer receiving already-built parts.
- Designate one authoritative owner collection when parts are heavily shared, so views
  and groupings never masquerade as the source of truth.

## Fidelity check
1. Claim: parts outlive their container in aggregation. Support: the capture's
   department/professor example states that closing a department leaves its professors in
   existence and available for reassignment, and deleting the department object leaves
   the professor objects alive.
2. Claim: dependency injection is presented as the best-practice endpoint. Support: the
   capture's bad-to-great progression labels constructor/setter provision of the
   developer list as the most flexible design, easing testing with mock developers.
3. Claim: shared references mean one update propagates to every container. Support: the
   capture's music-library walkthrough notes that a song appearing in two playlists is
   the same object in both, so an artist's metadata change shows up in each playlist
   automatically.
