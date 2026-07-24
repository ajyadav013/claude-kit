---
source: https://blog.algomaster.io/p/solid-principles-explained-with-code
author: ashishps1 (AlgoMaster newsletter)
license-note: ideas absorbed in own words; no text or code reproduced
---

# SOLID in practice: five refactor stories, one per principle

## What it teaches

A tour of Robert C. Martin's five SOLID principles, each taught through the
same rhetorical move: show a small design that violates the principle,
explain the concrete failure mode it invites, then show how a restructure
fixes it. The article's value is less in the definitions (which are the
classic ones) than in the choice of violation scenarios, which map each
abstract rule to a recognizable everyday design mistake. Note: the capture
contains the prose narration around the code samples but the code blocks
themselves did not survive extraction; the designs are still fully
reconstructible from the surrounding explanation.

The five refactor stories:

1. **Single Responsibility.** A user-management class that bundles
   authentication, profile management, and email notification has three
   reasons to change; touching one concern risks silently breaking another.
   The fix is splitting into three classes, one concern each, so change
   blast-radius shrinks to the class that owns the concern.
2. **Open/Closed.** A shape calculator that computes area/perimeter via
   type-specific logic must be edited every time a new shape appears. The fix
   is an abstract shape contract with one concrete class per shape, so new
   shapes are added by writing new code, not modifying tested code.
3. **Liskov Substitution.** A vehicle base type exposing an engine-start
   operation breaks when a bicycle subtype must implement an operation that is
   meaningless for it. The fix is generalizing the contract (a neutral "start"
   behavior) so every subtype can honor it honestly — cars start engines,
   bicycles start pedaling — and substitution never surprises callers.
4. **Interface Segregation.** A single fat media-player interface forces an
   audio-only player to carry video-playback and video-brightness operations
   it cannot meaningfully support. The fix is splitting into audio-focused and
   video-focused interfaces; a combined player implements both, everyone else
   implements only what they use.
5. **Dependency Inversion.** An email service hard-wired to one provider's
   client class couples high-level policy to low-level detail. The fix is an
   email-client abstraction that both the service and the concrete providers
   (the original one plus an alternative) depend on, making providers
   swappable.

## Key patterns & decisions

- **One reason to change per class (SRP)** — partition classes by concern so
  a change to authentication logic cannot ripple into notification logic.
- **Extend by adding, not editing (OCP)** — introduce an abstraction point
  where variation is expected, so new variants arrive as new classes and
  existing, tested code stays untouched.
- **Honest substitutability (LSP)** — design base-type contracts every
  subtype can genuinely fulfill; if a subtype must stub or fake an inherited
  operation, the contract is wrong, so generalize it.
- **Role-sized interfaces (ISP)** — split fat interfaces so clients depend
  only on operations they actually use; compose multiple small interfaces
  when a class truly needs both roles.
- **Depend on abstractions in both directions (DIP)** — high-level modules
  and low-level implementations both point at a shared interface, decoupling
  policy from vendor/provider detail and enabling swap-in replacements.
- **Violation-first pedagogy** — each principle is motivated by the concrete
  bug class it prevents (cross-concern side effects, regression risk in
  modified code, surprising subtype behavior, forced dead methods, vendor
  lock-in), which is a reusable way to teach or review against SOLID.

## When to apply / trade-offs

These are class-design defaults for object-oriented codebases, most valuable
at module seams where change is anticipated: authentication vs. notification
concerns (SRP), families of variants like shapes or providers (OCP, DIP), and
public contracts consumed by heterogeneous clients (ISP, LSP). The article
frames the payoff as maintainability and reduced bug risk during change. It
does not itself discuss overuse, but read alongside YAGNI/KISS (same course),
the OCP/DIP abstractions should be introduced where variation is real or
imminent, not speculatively — the shape and email examples both show the
abstraction being introduced at the moment a second variant is actually
needed.

## Fidelity check

1. Claim: the SRP example splits a three-concern user manager into three
   single-concern classes. Support: the capture describes a UserManager
   handling authentication, profile management, and email notifications, warns
   that changing one can inadvertently affect the others, and resolves it as
   three separate classes.
2. Claim: the LSP example fixes a bicycle-vs-engine mismatch by generalizing
   the base operation. Support: the capture explains that a bicycle
   implementing an engine-start method is the violation, and the fix replaces
   it with a general start behavior that a car maps to engine ignition and a
   bicycle maps to pedaling.
3. Claim: the DIP example decouples an email service from a specific
   provider via a client abstraction with two implementations. Support: the
   capture describes the service directly depending on a Gmail-specific
   client as the violation, then both the service and provider clients
   (Gmail and Outlook) depending on a shared email-client interface as the
   fix.
