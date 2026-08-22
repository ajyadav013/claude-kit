---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/digital-wallet-service.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Digital wallet: money movement modeled as accounts, transactions, and pluggable payment methods

## What it teaches

A classic object-oriented decomposition of a payments domain. The exercise separates
the *identity* layer (a user who owns things) from the *value* layer (accounts that
hold balances in a specific currency) from the *movement* layer (transactions that
record transfers between two accounts). Funding sources — cards, bank accounts —
are kept behind a shared abstraction so the wallet core never cares which
instrument money arrived from. Cross-currency support is isolated in a single
conversion component with its own rate table, and all wallet-wide operations flow
through one coordinating facade that also owns the concurrency story.

## Key patterns & decisions

- **Account as the unit of balance, not the user.** A user owns a list of
  accounts; each account carries its own currency and balance and exposes only
  deposit/withdraw operations. This gives multi-currency support for free (one
  account per currency) and keeps balance mutation localized.
- **Transaction as an immutable ledger record.** Every transfer produces a
  record with source, destination, amount, currency, and timestamp — the
  transaction history and statements are just projections over these records,
  never recomputed from balances.
- **Payment-method polymorphism.** An abstract payment-method base with concrete
  card and bank-account variants means new funding instruments are added by
  subclassing, not by editing the wallet core (open/closed principle applied to
  the riskiest integration surface).
- **Centralized currency conversion.** All exchange logic lives in one converter
  keyed by a rate table, so rate changes and rounding policy have a single home.
- **Singleton facade with synchronized mutation.** One wallet service instance
  coordinates user creation, transfers, and history retrieval, and serializes
  access to shared balances to keep concurrent transfers consistent.
- **Demo/driver class kept outside the domain.** Usage scenarios live in a
  separate demonstration entry point, keeping the domain model free of
  script-like orchestration.

## When to apply / trade-offs

- The account-per-currency + immutable-transaction split is the right starting
  shape for any balance-tracking feature (credits, quotas, spend limits), not
  just money.
- A process-wide singleton with coarse synchronization is fine for an interview
  or a single-node prototype, but it is the first thing to replace in a real
  service: you would want per-account locking or database transactions
  (SELECT ... FOR UPDATE / optimistic versioning) instead of one global monitor,
  and idempotency keys on transfers to survive retries.
- Static in-memory exchange rates are a stand-in; production needs a rate feed
  with staleness handling and an explicit rounding/precision policy (integer
  minor units, never floats).
- The design records history but does not model double-entry invariants
  (debits == credits); adding that check is the natural hardening step.

## Fidelity check

1. *Claim: balances live on accounts, each with its own currency.* Supported:
   the capture's class list describes an account entity holding an account
   number, a currency, a balance, and its transaction list, owned by a user who
   can hold several accounts.
2. *Claim: funding instruments sit behind a shared abstraction.* Supported: the
   capture describes an abstract payment-method base class with credit-card and
   bank-account concrete subclasses defining common payment-processing behavior.
3. *Claim: one singleton service owns coordination and thread safety.* Supported:
   the capture states the central wallet class follows the Singleton pattern and
   guards shared resources with synchronization while exposing user/account
   creation, transfers, and history retrieval.
