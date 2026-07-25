---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/library-management-system.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Library management: a small catalog domain guarded by one concurrent registry

## What it teaches

The smallest useful shape of a lend-and-return domain: two entity types (the
catalog item and the member) plus one coordinating registry that owns every
mutation — add/remove items, register/unregister members, borrow, return, and
keyword search. Instead of scattering locks across entities, the design leans on
concurrent map structures inside the single manager, so thread safety comes from
the choice of data structure rather than from explicit synchronization
sprinkled through the domain. Policy (borrow limits, loan duration) is framed as
rules the registry enforces at the borrow boundary, not as behavior baked into
the entities.

## Key patterns & decisions

- **Two-entity core: item + member.** The book carries identity (ISBN),
  bibliographic fields, and an availability flag; the member carries identity,
  contact details, and the list of currently borrowed items. Borrowing state is
  visible from both sides (item availability, member's held list).
- **Single registry as the only mutation path.** All catalog and membership
  changes go through one manager object, which is where invariants (an item
  can't be borrowed twice; a member can't exceed the cap) can be checked in one
  place.
- **Thread safety via concurrent collections, not lock scattering.** The manager
  stores catalog and member records in concurrent hash maps, so routine
  concurrent reads/writes are safe by construction without a global monitor on
  every operation.
- **Borrowing policy enforced at the transaction boundary.** Limits like
  max-books-per-member and loan duration are rules the manager applies when a
  borrow is requested — entities stay dumb data holders.
- **Search as a manager capability.** Keyword lookup over the catalog is exposed
  by the registry, keeping the query surface next to the data it indexes.
- **Singleton lifetime for the registry.** One process-wide manager instance
  models the fact that there is exactly one catalog.

## When to apply / trade-offs

- This is the template for any CRUD-plus-checkout feature: a registry object
  that owns concurrent collections and enforces policy at the borrow/return
  choke point is often all a small in-memory service needs.
- Concurrent maps make individual operations safe but do **not** make compound
  operations atomic: check-limit-then-borrow is a two-step sequence that can
  still race. A real implementation needs an atomic update per member/item
  (compute-style map updates, per-entity locks, or a database transaction).
- Availability-as-a-flag works at this scale; the moment there are multiple
  copies per title or reservations/holds, the flag must become a count or a
  separate loan record with due dates — the stated loan-duration rule already
  hints the flag is insufficient.
- Singleton registries trade testability for convenience; injecting the
  registry (or making it a plain instance) keeps the same design testable.

## Fidelity check

1. *Claim: all mutations funnel through one manager object.* Supported: the
   capture describes a single library-manager class, built as a Singleton,
   providing add/remove of books, member registration, borrow/return, and
   search.
2. *Claim: thread safety comes from concurrent data structures inside the
   manager.* Supported: the capture explicitly notes the manager uses
   ConcurrentHashMap-style structures to handle concurrent access to catalog
   and member records.
3. *Claim: borrowing rules such as caps and loan duration are system-enforced
   policy.* Supported: the capture's requirements list enforcement of a maximum
   number of simultaneously borrowed books and a loan-duration rule.
