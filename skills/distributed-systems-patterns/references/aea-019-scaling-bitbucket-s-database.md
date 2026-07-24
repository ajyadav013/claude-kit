---
source: https://www.atlassian.com/blog/atlassian-engineering/scaling-bitbuckets-database
author: Atlassian
license-note: ideas absorbed in own words; no text or code reproduced
---

# Offloading a stressed Postgres primary with LSN-aware read routing

## What it teaches

Bitbucket's two core Django services (website and public REST API) serve millions of requests
hourly, each averaging more than ten database queries, and nearly all of that traffic hit a
single Postgres primary — the read replicas existed but were effectively failover-only because
routing decisions lived in application code that almost nobody used. The post explains how the
team moved the bulk of read traffic to replicas transparently, without breaking read-your-writes
expectations, by tracking Postgres write-ahead-log positions per user. It is the canonical
worked example of solving the "replica lag vs. stale read" problem at the routing layer instead
of asking every developer to reason about it.

## Key patterns & decisions

- **Read/write split with a write pin.** Within a single request, reads go to a replica until
  the first write occurs; the write and everything after it in that request goes to the primary.
  This kills the intra-request race where you write then immediately fail to read your own data.
- **LSN tokens for cross-request read-your-writes.** Postgres assigns every write-ahead-log entry
  a log sequence number. After a user's write, the current LSN is saved; on the user's next
  request, only replicas whose replay position has reached that saved LSN are eligible to serve
  their reads. A user who just created a pull request will never be routed to a replica that
  hasn't replicated it yet.
- **Session-token storage out of band.** The per-user LSN lives in Redis (later Elasticache),
  keyed by the user's account ID, written by middleware at request end and read by middleware at
  request start — the same middleware layer that performs authentication.
- **Do it in the router, not in application code.** Because the logic sits at the database
  routing level, all existing and future code benefits with zero developer effort; the earlier
  opt-in "force a replica" mechanism failed precisely because it depended on individual
  developers.
- **Replica blacklisting.** Operational errors against a specific replica put it on a
  time-boxed denylist so traffic routes around it automatically.
- **Connection pooling via a proxy** (Envoy) between services and the Redis cluster; sharded
  Redis to spread the frequent small LSN writes.
- **Explicit latency budget.** The extra Redis and replica-catch-up checks add overhead; the team
  set roughly 10 ms as the acceptable cost and validated they stayed near it.
- **Measured outcome.** Production analysis predicted ~80% of primary traffic was movable;
  after rollout the majority of reads shifted to replicas and rows fetched from the primary on a
  busy day fell from over 800k to about 400k.

## When to apply / trade-offs

- Reach for this when a primary database is the bottleneck, replicas are idle, and the codebase
  is too large to annotate read paths by hand. It preserves per-user read-your-writes without
  global synchronous replication.
- Consistency guarantee is per-user only: user B may briefly not see user A's write. That was
  acceptable for Bitbucket's collaboration flows; it is not a substitute for strong consistency
  across users.
- Costs: extra infrastructure (session store, proxy), a small fixed latency tax on every request,
  and coverage gaps — any auth path that doesn't resolve a stable user ID (anonymous users,
  alternate auth methods) silently falls back to the old routing and gets no benefit.
- The pattern generalizes: any replicated store exposing a monotonic replication position can
  implement the same "causal token in a session store" scheme.

## Fidelity check

1. Claim: reads pin to the primary after the first write in a request. Support: the capture
   states the goal was routing all reads in a request to a replica until a write happens, with
   the write and everything after it going to the primary, to avoid users missing data they just
   wrote.
2. Claim: replica eligibility is decided by comparing replay position to a saved user LSN.
   Support: the capture describes saving the WAL log sequence number on write and, on later
   requests, selecting a replica that is at least as caught up as the user's stored LSN.
3. Claim: the rollout roughly halved primary read volume. Support: the capture reports rows
   fetched on the primary dropping from over 800,000 to 400,000 on a typical busy Wednesday, with
   added latency held near the ~10 ms tolerance they set.
