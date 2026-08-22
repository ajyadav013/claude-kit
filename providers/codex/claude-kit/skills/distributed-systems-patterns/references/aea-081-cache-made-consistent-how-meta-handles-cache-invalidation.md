---
source: https://engineering.fb.com/2022/06/08/core-infra/cache-made-consistent/
author: Meta Engineering (Lu Pan)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Observability-first cache invalidation: how Meta pushed TAO from six to ten nines of consistency

## What it teaches

Cache invalidation is hard not because the protocol design is exotic, but because a
dynamic cache mutates state on *both* paths — reads trigger fills, writes trigger
invalidations — and the interleaving of those two flows creates race windows that are
nearly impossible to reason about statically. Meta's core insight is to attack the
problem operationally rather than purely theoretically: build a false-positive-free
consistency *measurement* service first, then add targeted tracing only inside the
narrow time window where inconsistency can actually be introduced. That combination
turned week-long bug hunts into sub-30-minute diagnoses and moved TAO's measured
consistency from roughly six nines to ten nines.

The canonical failure mode: a fill request reads an old value from the database, a
write lands and its invalidation reaches the cache before the stale fill reply does,
and the late-arriving stale fill then overwrites the fresh entry — leaving the cache
permanently wrong. Versioning helps with conflict resolution, but caches evict, so
the version needed to reject the stale write may itself be gone. The article also
shows why stale caches matter: a stale replica of a user-to-storage-region mapping
caused a split-brain where two senders wrote a recipient's messages into two
different regions, which is user-visibly indistinguishable from data loss.

## Key patterns & decisions

- **Client-observable-invariant monitoring (Polaris pattern)**: a separate service
  poses as a cache client/replica, subscribes to invalidation events, and checks
  every replica against the invariant "cache eventually agrees with the source of
  truth" — treating anything a client cannot observe as a non-problem.
- **Zero-false-positive alerting as a hard requirement**: any noise trains humans to
  ignore the metric; the measurement pipeline is designed so a flagged inconsistency
  is always real.
- **Multi-timescale re-check queues with deferred expensive verification**: suspect
  samples are re-queried at escalating windows (1/5/10 minutes) and the costly
  cache-bypassing database read is only issued once a sample survives a full
  window — protecting the database the cache exists to shield.
- **Transient-vs-permanent inconsistency disambiguation flag**: probe queries carry a
  marker so the reply reveals whether the replica has already processed the relevant
  invalidation, separating replication lag from a stuck-forever stale entry.
- **Windowed consistency tracing instead of full logging**: rather than logging ten
  trillion daily fills, a stateful library keeps an index of recently written keys and
  records cache mutations only during the short post-write race window where fill and
  invalidation can collide; absence of an expected log line itself signals a lost
  invalidation.
- **Version fields for write ordering, with eviction as the known weakness**: older
  data must never clobber newer, but durability of version metadata cannot be assumed
  in a cache.
- **Error-handling paths are where consistency bugs hide**: the worked example was a
  conditional drop-if-older cleanup in an error handler that silently no-opped because
  the stale entry carried the latest version — triggered only by a rare interleaving of
  a two-table transaction, a racing fill, and a transient invalidation failure.
- **Consistency measured as a headline SLO**: "N nines of writes consistent within M
  minutes" makes cache-consistency work quantifiable and provable per fix.

## When to apply / trade-offs

Apply whenever a cache is actively invalidated rather than purely TTL-expired — the
authors explicitly claim the method generalizes down to "Redis in front of Postgres"
scale. The trade-offs: Polaris-style monitoring is an extra always-on service and its
verification traffic must be throttled to avoid hammering the source of truth;
windowed tracing accepts blind spots outside the race window in exchange for
tractable log volume. TTL-only caches are out of scope. The deeper lesson for any
team: designing a correct protocol and *operating* one are different disciplines —
budget for measurement and diagnosis infrastructure, not just the protocol.

## Fidelity check

1. Claim: Meta improved TAO's consistency from six nines to ten nines. Capture
   support: the post states TAO went from 99.9999 percent to 99.99999999 percent by
   one measure, with Polaris supplying those numbers at the five-minute timescale.
2. Claim: full logging of cache state changes is infeasible at this scale. Capture
   support: TAO serves over a quadrillion queries a day, so even at 99 percent hit
   rate there are more than ten trillion daily fills, which would turn a read-heavy
   workload into an extreme write load on any logging system.
3. Claim: the found-and-fixed bug lived in error-handling code doing a conditional
   drop. Capture support: a transient error during invalidation invoked a handler
   that drops a cache item only if its version is below a threshold; the inconsistent
   item held the latest version, so nothing was dropped and stale metadata persisted
   indefinitely, and tracing let on-calls locate this in under 30 minutes.
