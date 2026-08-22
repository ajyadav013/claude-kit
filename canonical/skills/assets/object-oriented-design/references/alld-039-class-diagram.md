---
source: https://algomaster.io/learn/lld/class-diagram
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Reading and drawing UML class diagrams: notation, relationship types, and the coupling spectrum

## What it teaches
How to model the static structure of an object-oriented system with a UML class
diagram. The chapter covers the three-compartment class box (name, data fields,
operations), the visibility prefix symbols, the stereotypes that mark special
class kinds (interfaces, abstract classes, enumerations), and — the core of the
lesson — the six relationship types that connect classes, ordered from loosest
to tightest coupling. It closes by walking a bookstore domain model that
exercises nearly every notation element in one picture.

## Key patterns & decisions
- Three-compartment class box: a class rectangle stacks its name on top, its
  data fields in the middle, and its operations at the bottom; fields and
  operations are written in a compact `visibility name: type` grammar, with
  optional multiplicity ranges and defaults for fields.
- Visibility markers: a one-character prefix on every member encodes access —
  public, private, protected, and a package-level marker specific to Java-style
  languages.
- Stereotype labels for special class kinds: a guillemet-style tag above the
  name distinguishes interfaces (contract only, no state), abstract classes
  (mix of implemented and italicized abstract operations, cannot be
  instantiated), and enumerations (a closed list of named constants such as
  order states or payment methods).
- Interface vs abstract class decision rule: reach for an abstract base when
  subclasses genuinely share state or common behavior; reach for an interface
  when otherwise-unrelated classes must honor the same contract with nothing
  shared underneath.
- Six relationship notations, each with a distinct arrow: dependency (dashed
  arrow — transient use inside a method, no stored field), association (solid
  arrow — a persistent field reference between independently-living objects),
  aggregation (hollow diamond — whole/part where parts outlive and can be
  shared across wholes), composition (filled diamond — whole/part where the
  whole creates and destroys the parts), inheritance/generalization (solid line
  with hollow triangle — a true "is-a" with inherited code), and realization
  (dashed line with hollow triangle — a class fulfilling an interface
  contract).
- Coupling spectrum as a design heuristic: the six relationships form a
  weakest-to-strongest ordering (dependency < association < aggregation <
  composition < inheritance < realization as a contractual bond), and the
  guidance is to always pick the weakest relationship that satisfies the need.
- Prefer composition over inheritance when "is-a" is dubious: inheritance is
  reserved for genuine type hierarchies with shared state/behavior, never for
  mere code reuse.

## When to apply / trade-offs
- Use a class diagram when you need a static snapshot of a domain model —
  interviews, design docs, onboarding material — not for runtime call ordering
  (that is a sequence diagram's job).
- The field-vs-parameter test is the practical disambiguator: if a reference
  lives only inside a method body it is a dependency; if it is stored as a
  field it is at least an association; ownership and lifecycle binding push it
  toward aggregation or composition.
- Aggregation vs composition hinges on lifecycle and sharing: parts injected
  from outside that survive the container (songs in a playlist) are
  aggregation; parts born and dying with the container (line items in an
  order) are composition.
- Weak coupling buys flexibility at the cost of less-explicit ownership; the
  chapter's default is to only escalate coupling when the domain forces it.

## Fidelity check
1. Claim: members carry a one-character visibility prefix with four levels.
   Support: the capture tabulates four markers — public, private, protected,
   and a package-scoped marker it flags as Java-specific — each controlling
   which classes may access the member.
2. Claim: abstract operations are typographically distinguished. Support: the
   capture's shape example shows the area and perimeter operations in italics
   to mark them abstract, while a color accessor is concrete and inherited
   as-is by all subclasses.
3. Claim: the chapter ranks all six relationships on a strength spectrum and
   says interviewers ask for it. Support: the capture explicitly lists the
   weakest-to-strongest ordering starting at dependency and ending at
   realization, notes it is worth memorizing for interviews, and derives the
   principle of preferring the weaker relationship where possible.
