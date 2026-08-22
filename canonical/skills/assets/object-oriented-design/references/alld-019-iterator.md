---
source: https://algomaster.io/learn/lld/iterator
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Iterator: decoupling traversal from storage so collections stop leaking their internals

## What it teaches

A behavioral pattern that moves "how do I walk through this collection" out of
the collection and out of the client into a dedicated traversal object. The
motivating anti-pattern is a playlist that hands its raw internal list to a
music player: the client can now mutate or wipe the list, is welded to the
list-based representation, must hand-roll every new traversal order, and is
hard to test in isolation. The fix is a minimal two-method traversal contract
(is there another element? give me the next one) produced by a factory method
on the collection, with the position state living in the iterator rather than
in the collection or the client.

## Key patterns & decisions

- **Never return the raw internal container.** Exposing the backing list gives
  every caller mutation rights (including clearing it) and couples all clients
  to the current representation; controlled accessors plus an iterator restore
  encapsulation.
- **Four-role structure.** An iterator interface (minimal: existence check +
  advance-and-return), a concrete iterator holding a collection reference and a
  cursor, an iterable-collection interface declaring the iterator factory, and
  the concrete collection that builds iterators on request.
- **Position lives in the iterator, not the collection.** If the collection
  tracked "current position" there could be only one walk at a time; separate
  iterator objects let many clients (or threads) traverse the same data
  simultaneously and independently.
- **Minimal collection surface for the iterator.** After refactoring, the
  playlist exposes only element-at-index and size — just enough for the
  iterator to work — instead of the whole list. Internal structure stays
  private.
- **New traversal = new iterator class, nothing else changes.** Reverse order,
  shuffle, filter-by-type, unread-only: each is one new iterator; the
  collection, the other iterators, and the client loop are untouched. This is
  the open/closed principle applied to traversal.
- **Uniform client loop across all traversal modes.** The consuming code is the
  same check-then-advance loop regardless of which iterator was requested; only
  the factory call differs. Filtering and skipping logic hides inside the
  iterator.
- **Single responsibility split.** The collection's one job is storing and
  managing elements; the iterator's one job is walking them; each now has
  exactly one reason to change.

## When to apply / trade-offs

- Use when clients need sequential access to an aggregate without depending on
  its representation, when multiple traversal strategies must coexist, or when
  simultaneous independent walks over the same data are needed.
- The pattern future-proofs representation changes: swapping the backing store
  (different list type, a set, lazy loads from a database) only touches the
  iterator, not client code.
- The remote-control analogy frames it: next/previous buttons work without the
  viewer knowing how the channel list is stored.
- Cost is a couple of extra small classes per collection; for a one-off
  internal loop over a stable structure that overhead may not pay. Most
  languages bake this pattern into their standard iteration protocols, so
  hand-rolling it matters mainly when you need custom traversal semantics.
- The notification-center example generalizes it: one store, three iterators
  (all, by-channel-type, unread-only), identical consuming loops — adding a
  time-windowed traversal later is one new class.

## Fidelity check

1. *Claim:* returning the internal list lets clients destroy the collection's
   state. *Capture support:* the chapter shows that nothing stops a caller
   from clearing the returned list outright, wiping the playlist — its lead
   example of broken encapsulation.
2. *Claim:* separate iterator objects exist chiefly to allow multiple
   concurrent traversals. *Capture support:* the capture's aside answers "why
   not put the traversal methods on the collection?" by noting a
   collection-tracked cursor permits only one walk at a time, whereas
   independent iterators each carry their own position — important in
   multi-threaded use or when comparing different positions.
3. *Claim:* new traversal behaviors require no changes to collection or client.
   *Capture support:* the extension section adds reverse and shuffle playback
   purely as new iterator classes, and the notification example stresses the
   client loop is byte-for-byte the same across all three traversal modes with
   only the iterator-creation call differing.
