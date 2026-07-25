---
source: https://algomaster.io/learn/lld/flyweight
author: algomaster.io (AlgoMaster / ashishps1)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Flyweight: sharing immutable state to keep object-heavy systems in memory budget

## What it teaches

The chapter motivates the Flyweight pattern with a text-editor scenario: a document rendered
character-by-character, where every character carries formatting (font family, size, color) plus a
screen position. Building a self-contained object per character means a half-million-character
document duplicates the same few formatting combinations hundreds of thousands of times. The
lesson is a memory-accounting one: only a tiny slice of each object's data (the position, roughly
a dozen bytes) is actually unique; the bulk (formatting, on the order of a hundred bytes) is
repeated, and at scale that redundancy costs tens of megabytes plus heavy garbage-collector and
CPU-cache pressure.

The pattern's fix is a disciplined split of object state into two categories:

- Intrinsic state — the shareable, context-independent portion (glyph symbol + formatting). It is
  stored once inside a flyweight object and made immutable, which is what makes concurrent sharing
  safe: no holder of the reference can mutate it out from under the others.
- Extrinsic state — the per-occurrence, contextual portion (x/y coordinates). It never lives in
  the flyweight; the client supplies it as arguments at call time (e.g., a draw operation that
  receives coordinates).

A factory is the second load-bearing piece. Clients never construct flyweights directly; they ask
the factory, which keeps a cache keyed by the full tuple of intrinsic fields and returns an
existing instance on a hit. Identical intrinsic combinations are therefore guaranteed to be the
same object in memory, and a counter on the factory lets you measure how much sharing you actually
got.

## Key patterns & decisions

- Intrinsic/extrinsic state split: classify each field as shareable-and-immutable vs
  per-occurrence, and store only the former inside the shared object.
- Extrinsic state passed as call arguments: operations on the flyweight take the contextual data
  (position) as parameters instead of reading it from fields.
- Factory-managed interning cache: a single factory keyed on the concatenated intrinsic fields
  guarantees deduplication and is the only construction path clients use.
- Immutability as the sharing safety guarantee: once created, a flyweight's fields never change,
  so thousands of referents cannot corrupt each other.
- Lightweight context wrapper: a thin per-occurrence object (reference to shared flyweight + the
  unique coordinates) is what the client actually collects in bulk.
- Cache-size introspection for verification: exposing the count of distinct flyweights lets tests
  assert that sharing is really happening (e.g., 10 rendered characters, 9 flyweights).
- Sharing granularity follows intrinsic equality: two visually identical glyphs in different
  fonts/colors correctly get separate flyweights because their intrinsic tuples differ.

## When to apply / trade-offs

Apply when a system must hold very many similar objects whose state is mostly repeated — the
chapter's second example is a game forest: thousands of tree placements but only a handful of
species, so the heavy species data (name, color, texture) is shared while each placement keeps only
a reference plus coordinates. The pattern's payoff scales with the ratio of instances to distinct
intrinsic combinations (10,000 trees / 15 species-type objects). Trade-offs implied by the design:
the client takes on responsibility for carrying extrinsic state; the factory becomes a mandatory
choke point for construction; and the split adds indirection that is pointless if objects are few
or their state is mostly unique. Immutability of the shared part is non-negotiable — mutable
flyweights would make sharing a correctness hazard rather than an optimization.

## Fidelity check

1. Claim: the motivating cost analysis says duplicated formatting dominates per-character memory.
   Support: the capture estimates roughly 100 bytes of formatting per object against about 12
   bytes of genuinely unique symbol-plus-position data, putting ~50MB of waste on a
   500,000-character document.
2. Claim: the factory dedupe is demonstrated with a concrete count. Support: the walkthrough
   renders 10 characters but ends with 9 flyweights, because the repeated letter in one word shares
   an instance while same letters in differently formatted words do not.
3. Claim: the pattern generalizes beyond text rendering via a game example. Support: the forest
   scenario shares species-level data (name, color, texture) across all trees of a kind, so a
   10,000-tree map needs only as many heavy type objects as there are species (15).
