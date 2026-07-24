---
source: https://algomaster.io/learn/lld/memento
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Memento: undo via opaque snapshots that never leak internal state

## What it teaches

The chapter builds undo for a text editor. The naive version makes the
*client* responsible for snapshots: read the editor's content out through a
getter, stash the string, and push it back in on undo. That works for one
string field but breaks encapsulation — the client now knows the editor's
state *is* a string — and every future state addition (cursor, selection,
formatting) forces changes in every call site that implements undo. Snapshot
duty is also easy to forget, leaving silent gaps in history.

Memento fixes this with three roles. The **originator** (editor) is the only
party that reads or writes its own private fields; it can package them into a
sealed snapshot object and later unpack one to restore itself. The
**memento** is that snapshot: immutable, minimal, and opaque to everyone but
the originator. The **caretaker** (an undo manager) owns the *lifecycle* —
deciding when to save and when to restore, keeping a LIFO history stack — but
never looks inside a memento. The payoff is demonstrated by an evolution
step: when cursor position must also be restorable, only the editor and its
memento change; the undo manager and the client are untouched.

## Key patterns & decisions

- **Originator/memento/caretaker role split**: the object that owns state
  creates and consumes snapshots; a separate manager stores them; nobody else
  ever interprets them.
- **Opaque snapshot contract**: the caretaker treats each memento as a
  sealed black box — store, order, hand back, never inspect — which is what
  preserves encapsulation while still enabling restore.
- **Immutable, minimal snapshots**: a memento is frozen at creation
  (private/read-only fields) and carries only what restoration needs; it
  holds no behavior of its own.
- **LIFO history stack for undo**: the caretaker pushes a snapshot before
  each risky operation and pops the latest on undo — last saved, first
  restored.
- **Save/restore as the only snapshot seam**: the originator's normal
  operations are unchanged; exactly two methods touch mementos, keeping
  state-capture orthogonal to day-to-day behavior.
- **Open/Closed growth path**: enriching what gets snapshotted (cursor,
  selection, scroll) is contained inside the originator + memento pair —
  external code compiles and behaves unchanged.

## When to apply / trade-offs

Use for undo/redo, checkpoint/rollback before risky operations, or state
versioning — anywhere an object must be rewindable without publishing its
internals. The trade-offs the design implies: snapshots copy state, so
memory grows with history depth and with state size (the chapter keeps
mementos "minimal" for this reason); and the caretaker adds an extra moving
part that is only worth it once state is non-trivial or restore points are
frequent. If the client legitimately needs to *read* the saved state, this
is the wrong pattern — opacity is the whole point.

## Fidelity check

1. *Claim: the naive approach leaks the editor's representation to the
   client.* The capture says the client fetching content and feeding it back
   into undo means the client knows the state is a string named content, and
   that adding cursor or formatting state would force every undo-implementing
   class to change.
2. *Claim: the caretaker never inspects memento contents.* The capture
   repeatedly defines the caretaker (the undo manager) as storing and
   returning mementos while treating them as black boxes, and notes its
   save/undo operations call only the originator's save/restore seam rather
   than any state getter.
3. *Claim: extending saved state touches only originator + memento.* The
   capture's "adding cursor position" section states the undo manager and
   client code did not change at all — only the memento and the editor — and
   frames this as the Open/Closed Principle in action.
