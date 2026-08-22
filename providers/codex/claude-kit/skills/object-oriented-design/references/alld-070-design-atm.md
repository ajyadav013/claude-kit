---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/atm.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# ATM design: layered facade over a banking service, transaction hierarchy, and a synchronized physical dispenser

## What it teaches

This classic problem separates an ATM into three concerns that are easy to
conflate: the user-facing terminal (authentication, menu of operations), the
bank-side ledger (accounts, balances, transaction processing), and the
physical cash mechanism. The requirements force interactions across a trust
boundary — the ATM never owns account truth; it asks a backend banking
service to validate cards/PINs and to apply debits and credits — plus
concurrency safety on both the shared account store and the single physical
dispenser.

The reference model has a card value object (number + PIN), an account
entity exposing debit and credit operations on its balance, an abstract
transaction base specialized into withdrawal and deposit variants, a banking
service holding accounts in a thread-safe map and executing transactions,
a cash dispenser whose dispensing is synchronized because the hardware is a
single mutually-exclusive resource, and an ATM class acting as the facade
that wires authentication, inquiry, withdrawal, and deposit flows through
the service and dispenser.

## Key patterns & decisions

- **Facade over collaborating subsystems**: the ATM class is a thin
  orchestration front; account logic lives in the banking service and cash
  handling in the dispenser, so each piece is replaceable (e.g., swap the
  backend for a network client) without touching the flows.
- **Transaction type hierarchy**: withdrawal and deposit extend an abstract
  transaction, giving each operation a uniform shape the banking service can
  process polymorphically — new operation types (transfer, bill pay) slot in
  as new subclasses.
- **Ledger authority stays server-side**: the ATM authenticates and
  requests; the banking service owns accounts and applies balance changes,
  modeling the real trust boundary between edge device and core banking.
- **Thread-safe account registry**: the service keeps accounts in a
  concurrent map so simultaneous sessions can resolve accounts without a
  global lock.
- **Mutual exclusion at the physical resource**: cash dispensing is
  synchronized — a correct recognition that hardware with one output slot is
  a critical section regardless of how parallel the software is.
- **Debit/credit as account methods**: balance mutation is encapsulated on
  the account entity rather than performed by callers poking a field,
  keeping the invariant (balance changes only via defined operations) in one
  place.

## When to apply / trade-offs

- The facade/service/device split maps directly onto any edge-device +
  backend system (POS terminals, kiosks, IoT actuators): keep truth in the
  service, keep hardware exclusivity at the device driver, keep the edge
  thin.
- The abstract-transaction hierarchy is clean for a handful of operation
  types but drifts toward the command pattern as operations acquire
  undo/audit/queuing needs; either way, reifying each operation as an object
  is what enables logging and retries.
- Missing from the toy (worth raising in interviews): atomicity across the
  ledger debit and the physical dispense — real ATMs need a reconciliation/
  reversal path when the dispenser fails after the debit; the capture's
  design synchronizes each side but does not describe a two-step commit.
- A concurrent map guards the registry, but per-account operations still
  need their own atomicity (debit is check-then-subtract); encapsulating
  mutation on the account entity is the hook where that locking belongs.

## Fidelity check

1. Claim: the design splits responsibilities among an ATM facade, a banking
   service, and a cash dispenser. Support: the capture describes the ATM
   class as the main interface that talks to the banking service and the
   cash dispenser to perform authentication, inquiry, withdrawal, and
   deposit.
2. Claim: transactions form an inheritance hierarchy with withdrawal and
   deposit specializations. Support: the capture names an abstract
   transaction base class extended by withdrawal and deposit transaction
   classes.
3. Claim: concurrency is handled with a thread-safe account map plus
   synchronized dispensing. Support: the capture states the banking service
   stores accounts in a concurrent hash map and the dispenser uses
   synchronization to stay safe when dispensing cash.
