---
source: https://algomaster.io/learn/system-design/idempotency
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Idempotency: engineering retry safety with keys, leases, and atomic reservation

## What it teaches

Why every distributed system needs operations that can be safely re-run, and
how to build that property when it does not come for free. The motivating
scenario: a response is lost in transit, the client cannot tell whether the
operation happened, and a naive retry double-charges a card. Idempotency means
repeating an operation yields the same intended effect as running it once —
"effect," not "byte-identical response." The chapter separates operations that
are naturally idempotent (setting a final state, deleting a known resource)
from those that must be *engineered* idempotent (payments, order creation,
email sends, job submission) via stable operation IDs, and then details the
full server-side machinery.

## Key patterns & decisions

- **Natural vs engineered idempotency**: absolute writes ("status = ACTIVE")
  repeat safely on their own; relative writes ("add 10 to inventory") and
  creations need a stable operation ID that converts "do X" into "apply
  operation #N exactly once."
- **Client-generated idempotency keys**: the key must exist before the first
  attempt is sent (otherwise a lost response strands the client), stay
  constant across retries of the same logical operation, differ between
  distinct operations, and be stored durably server-side.
- **Key scoping and request-hash binding**: scope keys by tenant/caller/
  endpoint/operation type to prevent cross-tenant collisions, and store a hash
  of the request body so the same key arriving with a different payload is
  rejected instead of silently answered with a stale result.
- **Atomic key reservation**: check-then-insert races — two concurrent retries
  can both pass the check and both execute. Reserve with a single atomic
  insert guarded by a unique constraint (or transaction/compare-and-set), and
  on conflict load the existing record to decide the response.
- **Lease-based in-progress records**: a reserved record carries an
  IN_PROGRESS status plus a lock-expiry timestamp; if the owner crashes before
  finishing, a later retry that finds an expired lease claims it and re-runs
  the work — which is why the guarded work itself must also be retry-safe.
- **Stored-response replay**: on completion the record captures the response
  status/body so a later duplicate gets the original answer back, sparing
  clients from treating a benign duplicate as an error.
- **In-progress duplicate strategies**: while the first attempt is still
  running, a concurrent duplicate can get a conflict response, an accepted
  response pointing at a pollable operation resource (best for long-running
  work), a brief blocking wait, or a stored partial-state answer.
- **External side-effect recovery path**: no local transaction spans a
  third-party API, so pass your idempotency key through to providers that
  accept one, persist a local attempt record before the outbound call, store
  the provider's charge/job ID as soon as known, and be able to query the
  provider to reconcile "the charge happened but our commit didn't."
- **Consumer-side dedupe at the business write**: message brokers deliver
  at-least-once, so dedupe in durable storage — ideally a unique constraint on
  the business table itself (e.g. unique shipment ID) rather than an
  in-memory set — and acknowledge/commit offsets only after the business write
  is durable.
- **Idempotency ≠ exactly-once**: the guarantee is one *intended effect*
  despite repeats, not proof the code ran once; broker exactly-once features
  stop at the broker's own boundary and never extend to external providers.
- **Retention as API contract**: idempotency records expire; document the
  window, because a retry arriving after expiry will be treated as a brand-new
  operation.

## When to apply / trade-offs

Mandatory for any retryable path with side effects: payment and order
endpoints, webhook handlers, queue consumers, background jobs, data pipelines.
HTTP semantics help (GET/PUT/DELETE are idempotent by definition, POST is
not, PATCH depends on whether it sets or increments) but method choice alone
never covers creation flows. Costs: a durable key table with careful atomicity,
lease-timeout tuning (long enough for slow-but-alive operations, short enough
that crashes do not block retries), retention/cleanup policy, and testing for
concurrent retries, crashes mid-flight, and broker redelivery.

## Fidelity check

1. *Claim: keys must be generated client-side before the first request.* The
   capture explicitly warns against minting the key only after the server
   receives the request, because a lost response leaves the client with no key
   to retry under.
2. *Claim: an expired lease lets a second request take over a crashed owner's
   work.* The status-lifecycle section describes a lock-until timestamp: if it
   is in the future the server answers "retry later," and if it has passed the
   duplicate extends the lease and runs the operation itself.
3. *Claim: the strongest consumer dedupe lives in the business table.* The
   messaging section says a shipments table with a unique shipment ID is
   stronger than an in-memory processed-set, and that offsets should be
   acknowledged only after the business write is durably stored.
