---
source: https://algomaster.io/learn/lld/prototype
author: algomaster.io (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Prototype pattern: self-cloning objects and the shallow/deep copy trap

## What it teaches

The chapter asks how you would copy an arbitrary object. Field-by-field
copying from outside fails three ways: private fields are unreachable without
breaking encapsulation; you must know the concrete class to construct the
copy, coupling the copier to it (an Open/Closed violation that also fights
polymorphism); and when your code holds only an interface reference you cannot
name a constructor at all. The resolution is to move cloning inside the
object: it exposes a clone operation and returns a configured duplicate of
itself, so callers copy through the interface without knowing the class.

The motivating scenario is enemy spawning in a game. Constructing each enemy
inline duplicates initialization logic everywhere, scatters the canonical
defaults across the codebase, and invites silently-wrong or missing fields.
Instead you build one fully-configured exemplar per enemy type, park it in a
registry keyed by name, and every spawn is a clone request followed by
optional per-instance tweaks. The template stays pristine.

## Key patterns & decisions

- Self-cloning as an encapsulation move: the object copies itself, so private
  state and concrete types never leak to callers.
- Clone through the interface: client code can duplicate objects it knows only
  abstractly, which constructors can never offer.
- Prototype registry: a keyed store of pre-configured exemplars centralizes
  default configuration; adding a variant is a registration, not new code
  paths.
- Registry must hand out clones, never the stored original: returning the
  prototype itself would let callers mutate the template and silently corrupt
  every future copy.
- Shallow vs deep copy discipline: primitives and immutable fields copy safely
  by value/reference, but every mutable reference field (lists, nested
  objects) must be recursively duplicated or original and clone will share
  state — the article flags this as the classic source of subtle,
  intermittent bugs.
- Clone-then-customize workflow: spawn a copy, then adjust the one or two
  fields that differ (e.g., a weakened enemy), keeping variants cheap.
- Nested deep-copy delegation: in the email-template example a recipient-list
  object exposes its own deep-copy operation that the outer clone calls,
  composing deep copies instead of one class knowing every nesting level.

## When to apply / trade-offs

Use Prototype when construction is expensive or configuration-heavy, when you
need many near-identical instances, or when code must duplicate objects known
only by interface. The cost is that every class in the object graph must
implement correct cloning, and a single missed mutable field degrades a deep
copy into a shared-state bug. For flat objects with immutable fields a shallow
copy is sufficient and cheaper — the chapter explicitly shows shallow cloning
working correctly until a mutable inventory list is introduced.

## Fidelity check

1. Claim: external copying breaks on encapsulation and class coupling.
   Support: the capture lists three problems — inaccessible private fields,
   needing the concrete class (OCP violation), and interface-only contexts
   where no constructor is knowable.
2. Claim: the registry returning originals would corrupt future clones.
   Support: the capture calls out that its lookup always returns a clone,
   because handing back the stored prototype lets clients modify the template.
3. Claim: missed deep copies cause cross-instance bleed. Support: the email
   example states that without deep-copying the nested recipient list, adding
   a recipient to one department's email would mutate every other department's
   email and the base template simultaneously.
