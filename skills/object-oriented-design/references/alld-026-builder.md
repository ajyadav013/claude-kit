---
source: https://algomaster.io/learn/lld/builder
author: algomaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Builder: step-by-step construction for many-optional-field objects

## What it teaches

How to construct objects that mix a few required fields with many optional ones
— the chapter's running example is an HTTP request with a mandatory URL plus
optional method, headers, query parameters, body, and timeout — without falling
into the telescoping-constructor trap. The naive route piles up overloaded
constructors of increasing arity; callers then pass positional nulls for fields
they don't care about, adjacent same-typed parameters invite silent argument
swaps, and every new optional field means adding or reshaping constructors and
risking existing call sites. The Builder moves configuration into a dedicated
companion object: callers name each field via a dedicated method, chain the
calls fluently in any order, and finish with a single build step that validates
and produces the final product — which can then stay immutable for its whole
life.

## Key patterns & decisions

- **Telescoping constructors as anti-pattern**: growing overload ladders with
  positional nulls are flagged as unreadable, error-prone, and unscalable; the
  builder replaces position with names.
- **Fluent chaining**: every configuration method hands back the builder,
  turning construction into one readable expression terminated by build().
- **Private product constructor + nested builder**: the product is only
  constructible through its builder (commonly a static nested class), which
  copies accumulated state into the product's fields at build time.
- **Immutability by construction**: because all mutation happens on the
  builder, the finished product can be frozen — the chapter calls out the
  thread-safety this buys.
- **Validation funnel at build()**: the single build step is the natural
  choke-point to check required fields and cross-field consistency before any
  object exists.
- **Order-independent configuration**: optional setters may run in any
  sequence; only required inputs are pinned (fed to the builder's own
  constructor).
- **Optional Director for shared recipes**: when many call sites need the same
  configuration (the chapter's case: every payment-service call wanting the
  same auth header, content type, and timeout), a director class encapsulates
  named preset build sequences instead of copy-pasted chains.
- **Builder as embedded DSL**: the closing example is a SQL SELECT builder
  where each method contributes a clause and the final step assembles the
  statement — the shape ORMs and query libraries use.

## When to apply / trade-offs

Use it when an object has enough optional knobs that constructor overloads or
setter soup become hazardous, when construction must be staged, or when you
want an immutable end product with a mutable assembly phase. The chapter's
Director guidance doubles as a duplication heuristic: direct builder use is
fine for one-off configurations, but the same chain copy-pasted across roughly
three sites signals it's time to name the recipe in a director/factory. Costs:
a builder roughly doubles the surface area per product class and adds
ceremony that trivial two-field objects don't deserve; in languages with named
and default arguments much of the motivation evaporates, so the pattern is most
load-bearing where parameters are positional.

## Fidelity check

1. Claim: the anti-pattern being replaced is a ladder of increasingly wide
   constructor overloads. Support: the capture names the telescoping
   constructor explicitly and lists its failure modes — swapped same-typed
   arguments, mandatory nulls for unused optionals, and breakage risk when
   adding parameters.
2. Claim: the finished product can be immutable and is created only through
   the builder. Support: the capture describes a private product constructor
   that copies the builder's state and states the built request cannot be
   modified afterward, describing this as thread-safe by design.
3. Claim: the Director is optional and justified by repeated identical
   configuration. Support: the capture presents a payment-API scenario where
   the same header/content-type/timeout setup would otherwise be duplicated
   across about twenty call sites, and a table saying direct builder use fits
   one-off cases while a director fits shared presets.
