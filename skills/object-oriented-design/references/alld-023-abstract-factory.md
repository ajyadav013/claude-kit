---
source: https://algomaster.io/learn/lld/abstract-factory
author: algomaster.io (AlgoMaster)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Abstract Factory: constructing consistent families of related objects

## What it teaches

The chapter presents the Abstract Factory creational pattern through a
cross-platform desktop app that must render native-feeling widgets (buttons,
checkboxes, text fields, menus) on both Windows and macOS. The naive
approach — OS-conditional instantiation of platform classes scattered through
the client — is taken apart on five fronts: nothing structurally prevents a
developer from pairing a Windows button with a macOS checkbox (a bug that
compiles fine and only shows up as a visually broken screen); every
UI-creating file needs its own platform check; there is no shared button
abstraction, so widgets cannot be handled polymorphically; each new platform
or widget type multiplies classes and conditional branches across the whole
codebase; and existing code must be edited for every extension.

The pattern's defining idea, which the chapter stresses as the differentiator
from Factory Method, is *families*: where Factory Method creates one product
at a time, Abstract Factory groups the creation of several products that must
be mutually compatible behind one interface. Five roles: the abstract factory
(one creation method per product type), concrete factories (each producing a
complete, internally consistent set for one platform or theme), abstract
products (the widget contracts clients program against), concrete products
(platform-specific realizations), and the client (which holds the factory by
its abstract type and never names a concrete class). The decisive property is
structural: because a platform's factory can only manufacture that platform's
products, mixing families becomes impossible rather than merely discouraged —
the type system enforces the invariant.

The wiring discipline matters as much as the classes: exactly one place — the
program's entry point or configuration — decides which concrete factory to
build, and it is injected into the client's constructor. A second worked
example, a notification system where each channel yields a message object and
a paired sender that would garble output if mismatched, generalizes family
consistency beyond UI theming.

## Key patterns & decisions

- **Family consistency as a compile-time guarantee**: route all creation
  through one factory per family so incompatible cross-family pairings have
  no code path, instead of relying on convention.
- **Abstract Factory vs. Factory Method distinction**: one product at a time
  versus a coordinated set of products that must interoperate.
- **Single composition point for concrete choices**: only the entry point or
  configuration references concrete factories; everywhere else sees abstract
  types.
- **Factory injection into the client**: the client receives its factory via
  the constructor and stores it abstractly, enabling whole-family swaps
  without touching client logic.
- **Polymorphic product contracts**: shared abstract product interfaces let
  any code accept "any button," which the conditional design could not offer.
- **Whole-family swap for theming and testing**: substituting one factory
  changes every produced object at once — useful for platform switches, light
  and dark themes, or test doubles.
- **Extension by new family, not by edits**: supporting a new platform or
  channel means one new factory plus its products; existing factories and
  clients stay untouched.

## When to apply / trade-offs

Apply when a system supports multiple configurations, variants, or
environments whose objects must be used together and stay stylistically or
functionally coherent — OS look-and-feel, themes, notification channels with
paired message/sender objects. The structural cost is the widest class
surface of the creational patterns: every new product *type* (say, adding a
text field) forces a new method on the abstract factory and an implementation
in every concrete factory, so the pattern favors stable product-type sets
with a growing number of families rather than the reverse.

## Fidelity check

1. *Claim:* The naive design allows silent family mixing. *Support:* The
   capture states nothing stops a developer from instantiating a Windows
   button next to a macOS checkbox — it compiles, tests may pass, and the
   defect only appears as a visually broken screen for the user.
2. *Claim:* The family concept is what separates this pattern from Factory
   Method. *Support:* The capture says the key word is families, contrasting
   Factory Method's one-product-at-a-time creation with a GUI factory that
   produces buttons, checkboxes, text fields, and menus sharing one visual
   style.
3. *Claim:* Concrete factory references are confined to a single startup
   location. *Support:* The workflow's first step says a configuration value
   or runtime check at application startup selects the concrete factory, and
   that this is the only place in the codebase referencing concrete factory
   classes.
