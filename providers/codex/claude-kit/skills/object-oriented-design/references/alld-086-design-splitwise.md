---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/splitwise.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Expense sharing: polymorphic split strategies over a pairwise balance ledger

## What it teaches
The heart of an expense-splitting app is two ideas working together. First, "how an
expense divides" is variable behavior, so the design captures it as an abstract
split concept with concrete variants — equal shares, percentage shares, and exact
amounts — attached per participant. An expense is then just the paid amount, the
payer, and a list of these split records; new division rules (say, share-based)
become new subclasses, not edits to the expense logic. Second, the running state of
who-owes-whom is not recomputed from expense history on every view: each user
carries a pairwise balance map against other users, updated incrementally as
expenses land. Settling up is modeled as an explicit transaction entity between two
users that zeroes or reduces a pairwise balance, keeping an auditable record
separate from the balances themselves. A singleton service owns users, groups,
expenses, balance updates, and settlement, and shared maps/lists use concurrent
variants because multiple members of a group can add expenses simultaneously.

## Key patterns & decisions
- Strategy-via-subclassing for split rules: an abstract split base with equal,
  percent, and exact-amount specializations — the classic open/closed extension
  point of this problem.
- Expense as an aggregate of payer, amount, description, and one split record per
  participant, so validation (shares summing to the total) has a single home.
- Materialized pairwise balances: each user holds a map of net balances against
  counterparties, updated on write instead of derived on read.
- Settlement as a first-class transaction entity (sender, receiver, amount)
  rather than a silent balance mutation — history and audit come free.
- Group as a scoping container aggregating members and their shared expenses,
  while balances remain user-to-user rather than group-owned.
- Singleton service as the single mutation path for users, groups, expenses,
  balance updates, and settlements.
- Concurrent map/list structures guarding shared state against simultaneous
  expense additions, per the consistency requirement.

## When to apply / trade-offs
The split-strategy hierarchy is the reusable takeaway for any domain where one
transaction fans out into per-party obligations under interchangeable rules
(invoicing, royalty distribution, cost allocation, payroll deductions).
Write-time balance materialization makes reads cheap but makes correctness fragile:
a bug in one update silently corrupts net positions, and concurrent structures
protect individual maps but not the multi-user invariant that all pairwise deltas
from one expense apply atomically — a real system wants a transactional ledger or
event-sourced balances. Notably, this design keeps raw pairwise balances and does
not attempt global debt-graph minimization (fewest settlement payments), which is
the natural follow-up extension interviewers probe for.

## Fidelity check
- Claim: split behavior is modeled as an abstract base with three concrete
  variants. Support: the capture describes an abstract split class extended by
  equal, percent, and exact-amount split classes for the different division
  methods.
- Claim: user balances are stored as a per-user map against other users rather
  than recomputed from history. Support: the capture lists the user entity as
  carrying a map that stores balances with other users, with the service
  updating balances as part of expense handling.
- Claim: settling up produces a dedicated transaction record between two users.
  Support: the capture defines a transaction entity holding sender, receiver,
  and amount, and says the service settles balances by creating transactions.
