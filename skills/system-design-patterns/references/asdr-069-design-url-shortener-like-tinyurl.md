---
source: https://algomaster.io/learn/system-design-interviews/design-url-shortener
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# URL shortener design: read-path obsession, three ID-generation lineages, and atomic uniqueness

## What it teaches

A full interview-style walkthrough of a TinyURL-class service, but the
underlying lessons generalize far beyond the toy problem. The stated workload
(ten million new links daily, reads outnumbering writes a hundred to one,
sub-50ms p99 redirects) forces every major decision: split write and read
services so they scale independently, stack caches in front of the database
on the read path, and treat unique short-code generation as the design's
intellectual core. The chapter walks three generations of ID generation —
hash-and-truncate, central counter, and Snowflake-style distributed IDs —
and closes with expiration, custom aliases, and click counting, each solved
by pushing correctness into atomic storage primitives or asynchronous
pipelines.

## Key patterns & decisions

- **Size the design from the read/write asymmetry** — back-of-envelope math
  (hundreds of write QPS vs. tens of thousands of read QPS at peak) justifies
  separate shortening and redirection services and dictates that all
  optimization budget goes to the redirect path.
- **Base62 code-length arithmetic** — seven characters over the alphanumeric
  alphabet yields trillions of combinations, decades of headroom at billions
  of links per year; the encoding avoids Base64's URL-hostile characters.
- **Deterministic hashing vs. counter vs. distributed ID as an evolution of
  trade-offs** — hashing (canonicalize, hash, truncate, Base62-encode) is
  stateless and dedupes identical URLs but truncation makes collisions
  inevitable at scale, and collision fallbacks (salt-and-rehash, suffix)
  reintroduce the database round-trip that statelessness was supposed to
  avoid; an atomic central counter guarantees uniqueness with one increment
  but is a throughput bottleneck, a write-path single point of failure, and
  leaks sequential, guessable IDs; the Snowflake-style 64-bit composite
  (timestamp + worker ID + per-millisecond sequence) decentralizes generation
  entirely at the cost of clock-skew sensitivity and a coordination service
  for worker-ID leases.
- **Shard the counter, obfuscate the sequence** — the counter approach scales
  by packing a shard ID into an ID's high bits with a local counter below,
  and hides sequentiality behind a reversible bit-shuffle (Feistel/XOR) so
  private links can't be enumerated.
- **Prefer 302 over 301 to keep control** — a permanent redirect lets
  browsers cache the mapping and bypass the service forever, killing
  analytics and updatability; a temporary redirect costs a round-trip per
  click but preserves tracking, expiry, and destination edits.
- **Waterfall read path** — browser cache, then CDN edge, then in-memory
  distributed cache, then a key-value database as source of truth, each layer
  populating the one above on a miss (cache-aside), with NoSQL chosen because
  the access pattern is billions of simple point lookups with no joins.
- **Atomic conditional writes kill the check-then-insert race** — two users
  claiming the same custom alias simultaneously is solved not in application
  code but by storage primitives that insert only if the key is absent
  (conditional put, lightweight transaction, or unique constraint), returning
  a conflict to the loser; custom aliases share the same keyspace as
  generated codes so the redirect path stays uniform.
- **Hybrid expiration** — check the expiry timestamp at redirect time for
  exact real-time behavior (passive), plus a low-frequency background sweep
  for storage hygiene (active), rather than betting on either alone.
- **Cache TTLs must be capped by the link's remaining lifetime** — otherwise
  a CDN or cache entry with a long TTL keeps serving a link after it expired;
  the fix is taking the minimum of the default cache TTL and time-to-expiry.
- **Buffered/streamed click counting** — direct per-click database increments
  create write contention; aggregate counts in a fast in-memory store and
  flush periodically, or graduate to an event pipeline (queue, stream
  processor, analytics store) when real-time multi-dimensional analytics is
  required.

## When to apply / trade-offs

- Any read-dominated key-value service (feature-flag lookup, config serving,
  vanity routing) inherits this shape: independent read/write scaling,
  layered caches, and NoSQL point-lookup storage.
- The ID-generation trilemma recurs everywhere unique identifiers are minted:
  choose hashing when deduplication is a feature, a central counter for
  modest scale and simplicity, distributed composite IDs when throughput and
  availability dominate — accepting NTP discipline and worker-ID coordination.
- The conditional-write pattern is the general cure for any "claim a unique
  name" feature (usernames, slugs, reservations); never rely on a read
  followed by a write.
- The TTL-capping rule applies to any cached entity with its own expiry
  (sessions, signed URLs, offers).
- Graceful degradation stance: with the database down, keep serving redirects
  from cache (possibly stale) and queue writes for retry — availability of
  the read path is worth more than freshness.

## Fidelity check

1. Claim: collision handling erases the statelessness advantage of the
   hashing approach. Support: the capture notes both resolution strategies
   (salted rehash, appended suffix) require at least one database lookup,
   adding write-path latency and complexity — the very costs deterministic
   generation was meant to avoid.
2. Claim: the Snowflake-style scheme caps per-worker throughput per
   millisecond and stalls when exceeded. Support: the capture describes a
   12-bit sequence allowing 4,096 IDs per worker per millisecond, with the
   worker forced to wait for the next clock tick once exhausted.
3. Claim: expired links can outlive themselves in caches unless TTLs are
   bounded. Support: the capture gives the example of a link expiring in five
   minutes while its CDN/cache entry carries a 24-hour TTL, and prescribes
   setting the cache TTL to the minimum of remaining link lifetime and the
   default TTL.
