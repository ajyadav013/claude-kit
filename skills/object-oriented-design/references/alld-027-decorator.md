---
source: https://algomaster.io/learn/lld/decorator
author: algomaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Decorator: stack behaviors by wrapping, not subclassing

## What it teaches

How to add optional features to an object at runtime by nesting wrappers rather
than minting a subclass for every feature combination. The motivating example
is a text renderer that must support bold, italic, and underline in any mix.
Inheritance forces one subclass per combination, and the count grows as
2^n - 1: three formatting features already demand seven subclasses, five demand
thirty-one, with the logic for each feature copy-pasted into every subclass
that includes it — and no way to toggle a single feature on a live object. The
decorator answer: every wrapper implements the same interface as the thing it
wraps and holds a reference to an inner instance, so the client can layer any
subset of features in any order around a plain core object, and the whole stack
still looks like one component from the outside.

## Key patterns & decisions

- **Combinatorial subclass explosion as the trigger**: when optional features
  multiply into 2^n - 1 inheritance variants, composition-by-wrapping is the
  escape hatch.
- **Interface-preserving wrappers**: each decorator implements the wrapped
  component's own interface, so callers cannot distinguish a bare object from
  a decorated stack.
- **Abstract decorator base**: a shared abstract wrapper holds the inner
  component reference and default delegation; concrete decorators extend it
  and each add exactly one feature.
- **Before/after augmentation with inward delegation**: a decorator does its
  extra work around a call to the inner object — the chapter traces an
  underline wrapper opening its tag, delegating through italic and bold layers
  to the plain text, then closing on the way back out.
- **Runtime, order-sensitive composition**: which wrappers are applied, in what
  order, and how many times is decided when the object is assembled, not at
  compile time.
- **Repeatable wrapping**: the same decorator may be applied more than once —
  the coffee-shop example stacks a milk add-on twice and its cost counts
  twice, something inheritance could only express with yet another subclass.
- **Linear class growth**: n independent features cost roughly n decorator
  classes plus a small fixed base (the chapter counts five classes for three
  text features versus eight under inheritance).

## When to apply / trade-offs

Apply when features are optional, independently toggleable, and meaningfully
combinable: formatting layers, priced add-ons (the chapter's second domain is a
coffee order where condiment wrappers each carry a price and extend the
description), and by extension the stream-wrapper and middleware shapes common
in libraries. Trade-offs: behavior is spread across many small objects, so
debugging means walking a chain of wrappers; ordering can silently matter
(tags nest differently depending on wrap order); and object identity gets
fuzzy — the outermost wrapper is not the same instance as the core, which can
bite code that compares references or checks concrete types. For features that
are always-on or mutually exclusive, plain fields or Strategy are simpler.

## Fidelity check

1. Claim: the inheritance approach scales as 2^n - 1 subclasses. Support: the
   capture gives the formula and the concrete progression — seven subclasses
   for three features, fifteen for four, thirty-one for five.
2. Claim: calls flow inward adding behavior, then results assemble outward.
   Support: the capture's step-by-step walkthrough has the outermost underline
   layer emit its opening markup, delegate through the italic and bold layers
   to the plain text core, and each layer emit its closing markup as control
   returns, yielding fully nested output.
3. Claim: the same decorator can be legitimately applied multiple times.
   Support: the coffee-order example explicitly applies the milk wrapper twice
   on one order, notes each application adds its cost again, and contrasts
   this with inheritance needing a bespoke combined subclass.
