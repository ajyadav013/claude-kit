---
source: https://algomaster.io/learn/lld/visitor
author: algomaster.io (AlgoMaster / ashishps1)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Visitor: adding operations to a stable class hierarchy via double dispatch

## What it teaches

The motivating scenario is a vector-graphics editor with a shape hierarchy (circle, rectangle)
that must support a growing set of unrelated operations: on-screen rendering, area computation,
SVG export, JSON serialization. Putting every operation as a method on every shape class bloats
each class with mixed responsibilities (geometry, drawing, serialization), forces edits to the
entire hierarchy whenever an operation is added (an Open/Closed violation with recompile-and-risk
costs), and simply isn't possible when the element classes come from a third-party library or
generated code you don't control.

Visitor relocates all operational logic out of the element classes into standalone visitor
classes — one visitor per operation, with one method per concrete element type. The elements keep
a single tiny obligation: an accept operation that takes a visitor and immediately calls back the
visitor's method matching the element's own concrete type, passing itself along. This two-step
call is double dispatch: the executed behavior is selected by the combination of element type and
visitor type, and the element's self-identification means no runtime type inspection
(instanceof chains or type switches) is ever needed — the right overload resolves statically.

The chapter's analogy is a house inspection: the house doesn't know how to evaluate its own
wiring or pipes; it just admits specialists (plumber, electrician, structural engineer), and a
new kind of audit means hiring a new inspector, not remodeling the house. The refactored graphics
system demonstrates two visitors (area calculation and SVG export) operating over the same shape
collection, and adding a hypothetical JSON exporter is a new visitor class with zero changes to
the shapes.

## Key patterns & decisions

- Operation-per-visitor extraction: each cross-cutting operation becomes its own class, leaving
  element classes as clean data holders.
- Double dispatch through an accept callback: the element calls the visitor back with itself, so
  behavior is chosen by both concrete element type and concrete visitor type at compile time.
- Elimination of runtime type checks: the accept mechanism replaces instanceof ladders and type
  switches for type-dependent behavior.
- Visitor interface as a type roster: one visit method per concrete element type, making the set
  of element kinds an explicit compile-time contract.
- New behavior without touching structure: adding an operation means writing one new visitor;
  the element hierarchy and existing visitors stay untouched (Open/Closed).
- Applicability to unmodifiable hierarchies: works even when element classes are third-party or
  generated, since they only need the minimal accept hook.
- Per-operation testability: each visitor encapsulates exactly one concern and can be unit-tested
  in isolation against the element types.

## When to apply / trade-offs

Best when the object structure is stable but the set of operations over it grows — the chapter
names ASTs, documents, and UI element trees as canonical hosts. The pattern's asymmetry is the
key trade-off (implied by the visitor interface's one-method-per-element-type shape): cheap to
add operations, expensive to add element types, since every new concrete element forces a new
method on the visitor interface and on every existing visitor. It also requires the element
classes to expose enough data for external visitors to work, and demands at least the small
accept hook in each element — so a hierarchy you truly cannot touch at all still needs that
minimal seam. If the element set churns faster than the operation set, plain polymorphic methods
are the better fit.

## Fidelity check

1. Claim: the pattern is pitched partly at hierarchies you don't own. Support: the capture's
   problem section asks what happens when shape classes belong to a third-party library or are
   generated code, where directly adding behavior isn't feasible.
2. Claim: double dispatch removes the need for type inspection. Support: the text explains that
   the element invoking the visitor's type-specific method with itself resolves the concrete
   type at compile time, eliminating instanceof checks and type switches.
3. Claim: extension is demonstrated as visitor-only. Support: the walkthrough implements area
   and SVG-export visitors over the same shapes and states that a JSON exporter would be a new
   visitor added without touching any shape class.
