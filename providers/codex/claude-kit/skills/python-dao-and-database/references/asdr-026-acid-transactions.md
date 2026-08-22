---
source: https://algomaster.io/learn/system-design/acid-transactions
author: AlgoMaster
license-note: ideas absorbed in own words; no text or code reproduced
---
# ACID transactions: what each guarantee actually covers, and where it stops

## What it teaches
Using the classic two-account money transfer as the running example, this chapter
explains why a group of related writes must commit or roll back as a single unit,
then unpacks each ACID letter as a distinct, bounded promise. Its strongest theme
is scoping: ACID protects state *inside one database*; it does not make the
application correct, does not know your business rules, and cannot un-happen an
external side effect like a payment API call or an email. The chapter also treats
isolation-level choice and durability configuration as design decisions with real
costs, not checkboxes.

## Key patterns & decisions
- **Transaction as the unit of correctness**: bracket related writes (debit +
  credit; stock decrement + order insert) so a crash mid-sequence cannot leave a
  half-finished state; the engine's undo/redo bookkeeping makes rollback possible.
- **Consistency is layered, not delegated**: the schema enforces keys, references,
  NOT NULL and CHECK-style rules; the transaction groups related changes; the
  application encodes business rules the database cannot express; cross-system
  agreement needs workflows, retries, and repair jobs on top.
- **Name the concurrency anomalies**: dirty read, non-repeatable read, phantom
  read, lost update, and write skew are the failure modes isolation levels exist
  to prevent — reason about which ones your workload can tolerate.
- **Isolation level as an explicit trade**: from read-uncommitted up to
  serializable, each step buys anomaly protection at the price of more blocking,
  more aborts, or mandatory retry loops; identically named levels behave
  differently across PostgreSQL, MySQL/InnoDB, and SQL Server, so verify against
  your actual engine.
- **Inventory-oversell defenses**: when two buyers race for the last unit, prevent
  double-sale with one of: a conditional update guarded by the remaining-stock
  predicate, an explicit row lock at read time, a uniqueness-enforced reservation
  record, or serializable isolation plus retries.
- **Isolation implementation menu**: engines mix locking, multi-version
  concurrency control (readers see a snapshot while writers make new versions),
  range/predicate locks, and optimistic conflict detection — each with its own
  concurrency, memory, or retry cost; there is no free isolation.
- **Durability via write-ahead logging, within stated limits**: the recovery
  record is persisted before the data page is trusted, so replaying the log after
  a crash restores committed work; durability is a promise only for the failure
  classes the configuration covers, and relaxed commit-flush settings or
  asynchronous replication can still lose acknowledged writes.
- **Keep transactions short and side-effect-free**: slow external calls inside a
  transaction hold locks/versions and stall others; rollback cannot undo external
  actions, so bridge to other systems with idempotency keys, outbox tables,
  retries, and sagas rather than by stretching the transaction.

## When to apply / trade-offs
Reach for transactions whenever multiple records must change together in one
database, and choose the isolation level per workload rather than accepting the
default blindly — read-committed still permits lost updates and write skew.
Relax durability (delayed log flushes) only for rebuildable data such as caches
or analytics buffers, never for payments, orders, identity, or compliance
records. The moment a flow spans a payment processor, message send, or another
service, stop expecting rollback to save you and switch to idempotent, retryable
workflow patterns. The chapter is introductory but unusually honest about
engine-to-engine divergence; nothing here is novel, but it is a clean checklist
against the most common transaction misconceptions.

## Fidelity check
1. Claim: the chapter frames consistency as shared across schema, transaction,
   application, and cross-system workflow layers. Support: the capture explicitly
   assigns constraint enforcement to the schema, grouping to the transaction,
   inexpressible business rules to application code, and retries/duplicate
   handling/repair to external workflows.
2. Claim: identically named isolation levels differ across engines. Support: the
   capture warns that REPEATABLE READ in PostgreSQL, REPEATABLE READ in
   MySQL/InnoDB, and SQL Server's settings are not identical despite similar
   names, and says to check actual engine behavior.
3. Claim: durability is bounded and configurable, not absolute. Support: the
   capture states durability covers only the failure cases the database is set up
   to handle, describes WAL replay after a crash, and notes some databases
   acknowledge commits before every log flush while async replication can drop
   recently acknowledged writes during failover.
