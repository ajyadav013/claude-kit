---
source: https://algomaster.io/learn/system-design/cap-theorem
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# CAP as a failure-mode question, not a database label

## What it teaches
CAP is widely misquoted as "pick two of three." Its actual content is
narrower and more useful: when replicas of a data system cannot talk to each
other, each affected operation must either return possibly-stale state
(staying available) or refuse/delay (staying consistent) — no protocol lets
an isolated replica know about a write it never received. Partition
tolerance is not a menu option for distributed systems; networks *will*
fail, so the only real design decision is what each operation does when
they do. The chapter also carefully redefines the letters: CAP consistency
is close to linearizability (fresh read-after-write), not ACID consistency,
and CAP availability means non-error responses from non-failing nodes, not
uptime or speed.

## Key patterns & decisions
- **Per-operation, not per-database, CAP posture** — the same product
  legitimately runs a CP path for orders and payments next to an AP cache
  for catalog browsing and an eventually consistent search index; labeling
  a whole database "CP" or "AP" is too coarse to be actionable.
- **Start from the invariant, not the acronym** — first list what must
  never happen (double charge, oversell, stale permission grant, two owners
  of one lock), then map only those paths to CP behavior; everything else
  is a candidate for availability with staleness.
- **CP mechanics during partition** — reject minority-side writes, require
  quorum, route to a leader, or block until heal/timeout; consensus groups
  (Raft/Paxos) behave this way for the data they govern and go unavailable
  when no majority can form.
- **AP mechanics during partition** — serve stale reads, accept writes on
  multiple sides, queue replication, and reconcile afterward with
  application-specific merge rules (a cart merges as a union of items; a
  bank withdrawal cannot merge at all).
- **Conflict resolution is a designed feature, not a default** —
  last-write-wins silently loses edits; important AP data needs versioning,
  idempotency, reconciliation jobs, and user-visible repair flows.
- **PACELC extends CAP to the healthy-network case** — during a partition
  choose availability vs consistency; otherwise choose latency vs
  consistency, which is the trade engineers actually make daily (local
  replica reads vs cross-region quorum).
- **"Eventually" is not an SLO** — AP paths need an explicit staleness
  budget and exposed freshness (timestamps, sync states) when users or
  downstream systems care.
- **Measure the failure posture** — replication lag, quorum failure rate,
  conflict rate, stale-read rate, consumer lag, and recovery time are the
  observability counterparts of a CAP decision.

## When to apply / trade-offs
- CP-style behavior belongs where stale or divergent state does real
  damage: ledgers and balances, scarce inventory reservation, distributed
  locks and leases, permission/API-key revocation, quota enforcement,
  exactly-once workflow transitions, and production config or model
  rollout state. In these paths a clean error beats a confident wrong
  answer.
- AP-style behavior fits derived or mergeable data: feeds, notifications,
  carts with merge logic, search and vector indexes, counters, analytics,
  and CDN/edge caches — places where coordination cost exceeds the value
  of perfect freshness.
- "CA" is only coherent when partitions are outside the failure model
  (essentially a single healthy node); a distributed system that never
  specifies partition behavior hasn't escaped CAP, it has just left the
  behavior undefined.
- With managed multi-mode databases you cannot infer guarantees from
  buzzwords; interrogate the specific operation: which replica accepts the
  write, what acknowledgement counts as success, can a stale replica serve
  the read, what happens when the leader is unreachable, and whether
  secondary indexes/streams/caches share the same guarantee.

## Fidelity check
1. Claim: the trade-off only bites during partitions, and only for
   affected operations. Capture support: the chapter's two-region price
   update example — once the inter-region link drops, the unsynced region
   can either answer with the old price (available, stale) or error/delay
   (consistent, unavailable); healthy networks can give both properties.
2. Claim: CAP's letters don't mean what engineers colloquially assume.
   Capture support: the text stresses CAP availability is "non-error
   response from a non-failing node" (not uptime/SLO), and CAP consistency
   is a strong read-after-write/linearizability-like guarantee (not ACID's
   C).
3. Claim: permission revocation is a canonical CP path. Capture support:
   the API-key example — after a revocation is acknowledged, a partitioned
   replica that still honors the key is a security bug, which is why
   enforcement paths for access control are listed under CP use cases.
