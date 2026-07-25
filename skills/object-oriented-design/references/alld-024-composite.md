---
source: https://algomaster.io/learn/lld/composite
author: algomaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Composite: one interface for leaves and trees

## What it teaches

How to model part-whole hierarchies (file systems, org charts, UI trees) so that
client code never has to ask "am I holding one thing or a group of things?" The
chapter motivates the pattern by first building a file explorer the naive way —
a File class and a Folder class with no shared contract, where the folder holds
untyped children and probes each one's runtime type before acting on it. Every
operation (total size, pretty-printing, recursive delete) then re-implements the
same type-dispatch, and each newly introduced item kind (a shortcut, a
compressed archive) forces edits to every existing operation. The fix is a
single component abstraction that both leaves and containers implement, with
containers holding children typed to that same abstraction, so recursion falls
out of ordinary polymorphic dispatch.

## Key patterns & decisions

- **Uniform component interface**: leaves and composites expose identical
  operations, so callers are structurally unable to special-case them.
- **Recursive composition**: a container's children are typed to the component
  abstraction itself, which makes arbitrary nesting depth free — a folder of
  folders needs no extra machinery.
- **Aggregate-by-delegation**: a composite implements an operation by fanning
  it out to children and combining results (sum sizes, indent-print, delete
  children then self); a leaf just answers for itself.
- **Type checks as a design smell**: repeated runtime-type inspection plus
  downcasting in every method is the signal that a shared abstraction is
  missing.
- **Open/Closed via new leaf kinds**: adding a new item type is one new class
  implementing the component interface; no existing operation changes.
- **Root-call ergonomics**: the client invokes one method on the tree root and
  the whole subtree answers — the same call is meaningful at any node (the
  chapter's org-chart version computes payroll for the whole company from the
  CEO node or one team's cost from a team-lead node, with identical client
  code).

## When to apply / trade-offs

Apply when the domain is genuinely tree-shaped and you want the same verbs to
work on an element and on a grouping of elements: filesystem items, nested UI
containers, menu trees, reporting hierarchies. The chapter's second worked
domain — managers containing employees and other managers, with rolled-up
salary and headcount — shows the pattern transplants cleanly across domains.
Trade-offs to weigh: the shared interface can become lowest-common-denominator
(child-management methods either pollute the leaf's contract or live only on
the composite, sacrificing full uniformity); and adding brand-new *operations*
(rather than new node types) still touches every class unless you pair it with
something like a visitor, which the chapter mentions as the extension route.
Skip it for flat collections — a plain list with a loop is simpler.

## Fidelity check

1. Claim: the naive design duplicates type-dispatch across every operation.
   Support: the capture's "what's wrong" section lists repetitive instanceof-
   style checks and downcasting appearing in each of the size, print, and
   delete methods as its first defect.
2. Claim: the pattern is defined by two properties — a uniform interface and
   recursive composition. Support: the capture explicitly names exactly these
   two characteristics as defining the pattern, with composites holding
   collections of components that may themselves be composites.
3. Claim: the same call works at any level of the tree with unchanged client
   code. Support: the org-hierarchy example states that invoking the salary
   roll-up on the top executive yields company-wide payroll while invoking it
   on a team lead yields that team's cost, without altering the caller.
