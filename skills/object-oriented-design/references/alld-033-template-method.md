---
source: https://algomaster.io/learn/lld/template-method
author: algomaster.io (AlgoMaster / ashishps1)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Template Method: freeze the workflow skeleton, delegate only the varying steps

## What it teaches

The chapter uses a report-export feature (CSV and PDF today, Excel coming) to show what happens
when several implementations each own an identical multi-step workflow: prepare data, open the
file, write a header, write rows, write an optional footer, close the file. Only the header and
row formatting genuinely differ by format, yet the naive design repeats the entire sequence in
every exporter class. Four failure modes follow: boilerplate duplicated per format, shared-logic
changes that must be applied N times (miss one and that format silently diverges), nothing
preventing a developer from reordering or dropping steps in one exporter, and no clear boundary
between shared plumbing and format-specific customization.

Template Method inverts this: a single abstract base class owns one method that encodes the fixed
step sequence. That template method calls three kinds of steps — concrete shared steps implemented
in the base, abstract steps each subclass must supply (the format-specific parts), and hooks with
harmless defaults that subclasses may optionally override (e.g., a footer that only the PDF
exporter uses for page numbers). The template method itself is sealed against overriding
(final/non-virtual), so subclasses can never alter ordering or skip stages — they fill in blanks
but never control when their code runs.

The chapter is explicit about a design judgment call: this is one of the rare patterns where
inheritance beats composition, because the base class must ship real sequencing logic that an
interface cannot carry. It also frames the payoff as Open/Closed in action — adding the Excel
format later is one new subclass with a few overrides and zero edits to the base or the existing
exporters.

## Key patterns & decisions

- Algorithm skeleton in a sealed template method: the base class fixes step order and forbids
  subclasses from overriding the orchestrating method itself.
- Three-tier step taxonomy: concrete shared steps, mandatory abstract steps, and optional hooks
  with default (often empty) bodies.
- Hooks for opt-in behavior: subclasses that need extra behavior (footer/page numbers, member
  discounts) override the hook; everyone else silently inherits the no-op default.
- Inversion of control ("don't call us, we'll call you"): subclasses supply step bodies but the
  base class decides when they execute.
- Deliberate use of inheritance over composition: justified because the shared artifact is
  sequencing logic, which an interface cannot enforce.
- Open/Closed extensibility test: a new variant (Excel exporter, new order type) is exactly one
  new subclass, with all existing classes untouched.
- Consistency as a first-class goal: locking the sequence in one place eliminates the
  drift-toward-inconsistency risk of independently maintained workflows.

## When to apply / trade-offs

Apply when multiple implementations share a well-defined, ordered sequence of steps and differ
only in a minority of those steps — the chapter's second example is an e-commerce order pipeline
(validate, total, discount, pay, confirm) where standard, Prime, and international orders each
override only the hook relevant to them (discounting vs localized confirmation). The trade-off is
inheritance coupling: every variant must be a subclass of the base, subclass authors must
understand which steps are required vs optional, and the fixed skeleton is a constraint — if a
variant genuinely needs a different ordering, the pattern is the wrong fit. Hooks mitigate
rigidity but each hook widens the base-class contract that all future subclasses inherit.

## Fidelity check

1. Claim: the template method must be non-overridable to guarantee ordering. Support: the capture
   states the skeleton method is typically marked final (Java/C#) or non-virtual (C++) precisely
   so subclasses cannot reorder or skip steps.
2. Claim: hooks let one format add a footer without burdening others. Support: in the worked
   refactor, the PDF exporter overrides the footer hook to emit page numbers while the CSV
   exporter leaves the empty default in place.
3. Claim: the chapter positions this as a legitimate inheritance use-case. Support: it argues an
   abstract class is required (not an interface) because only a class can hold a concrete method
   that invokes other steps in an enforced sequence, calling this one of the few patterns where
   inheritance is the right tool.
