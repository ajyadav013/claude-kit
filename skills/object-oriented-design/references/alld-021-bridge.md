---
source: https://algomaster.io/learn/lld/bridge
author: algomaster.io (AlgoMaster)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Bridge: splitting one class into two independently varying hierarchies

## What it teaches

The chapter motivates the Bridge structural pattern with a cross-platform
graphics library that must draw several shapes (circle, rectangle) using
several rendering strategies (vector, raster). The naive answer — one
subclass per shape-times-renderer combination — is dissected as a
combinatorial trap: 2×2 already yields four classes, a third renderer makes
six, and every additional shape multiplies again. Worse, each of those
subclasses welds two unrelated concerns together (what the thing is versus
how it gets drawn), so neither concern can be reused or extended alone, and
supporting a new rendering engine means revisiting every shape.

Bridge's answer is to cut the class along its two axes of variation and
connect the halves by composition. One hierarchy holds the abstraction —
domain-facing objects like shapes that know their own properties and expose
high-level operations. The other holds the implementor — engine-facing
objects that expose primitive low-level operations. The abstraction keeps a
reference to an implementor and, when asked to perform a high-level
operation, translates it into calls on that reference. Four roles emerge:
the abstraction (declares the domain operation, holds the implementor),
refined abstractions (add domain state such as radius or width/height),
the implementor interface (declares primitive operations), and concrete
implementors (each realizing those primitives with a particular technology).
Crucially, neither side knows the other's internals: a shape does not know
whether pixels or vectors come out, and a renderer does not know which shape
invoked it.

The remote-control analogy anchors it: remotes (abstraction hierarchy) and
televisions (implementation hierarchy) evolve separately, coupled only by
the signal between them. A second worked example builds remotes of differing
sophistication driving interchangeable devices, showing the same object
serving multiple abstractions at once.

## Key patterns & decisions

- **Identify orthogonal dimensions of variation**: when a class varies along
  two independent axes, splitting beats subclassing every combination.
- **Composition as the bridge**: the abstraction delegates to a held
  implementor reference at runtime instead of inheriting behavior, keeping
  both hierarchies shallow.
- **High-level to primitive translation**: the abstraction's job is to
  convert a domain request ("draw me") into implementor primitives ("render
  a circle of this radius").
- **Mutual ignorance across the bridge**: neither hierarchy references the
  other's concrete types, so each grows by adding exactly one class.
- **Runtime mix-and-match**: because the implementor is injected, pairings
  can be chosen or swapped dynamically (e.g., per device or user context).
- **Class-explosion arithmetic as the smell test**: if adding one variant on
  either axis forces N new classes rather than one, the hierarchy is fused
  and wants a bridge.

## When to apply / trade-offs

Reach for Bridge when you can name two (or more) independent reasons a class
changes — shape vs. rendering tech, control vs. platform — and the
combination count is starting to bite, or when the implementation must be
switchable at runtime. The implicit cost is indirection: every operation now
crosses an interface boundary, and the primitive operations on the
implementor side must be designed to serve all current and future
abstractions, which takes upfront interface care. For a single axis of
variation, Strategy-like composition or plain subclassing is simpler.

## Fidelity check

1. *Claim:* The naive design's cost grows multiplicatively. *Support:* The
   capture works the arithmetic explicitly — two shapes times two renderers
   equals four classes, and adding a third renderer such as OpenGL pushes it
   to six.
2. *Claim:* The pattern is defined by two properties: independent variation
   and composition over inheritance. *Support:* The capture names exactly
   these two characteristics, stating that adding a shape touches no
   renderer, adding a renderer touches no shape, and that the abstraction
   holds and delegates to an implementor object rather than inheriting.
3. *Claim:* Concrete implementors are shape-agnostic. *Support:* The
   capture's walkthrough notes the vector engine has no idea a circle called
   it — it merely received a radius and produced its output.
