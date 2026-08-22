---
source: https://algomaster.io/learn/system-design/client-server-architecture
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Client-server architecture: the split, the tiers, and what production adds

## What it teaches

A system-design primer on the request/response split: one program asks, another
program decides, does the work against shared protected resources, and answers.
The chapter's core argument is that the pattern itself is trivial — the real
engineering is everything production wraps around it (DNS, TLS, load balancers,
caches, queues, observability) because real systems face many users, hostile
inputs, flaky networks, and variable load. It walks the request lifecycle,
classifies systems by tier count, explains why centralization is the point,
then inventories the failure modes and scaling levers.

## Key patterns & decisions

- **Server as the trust boundary** — clients can be outdated, offline, or
  tampered with, so authorization, validation, limits, fraud checks, and audit
  logging must be enforced server-side; hiding a button in the UI is not access
  control.
- **Secrets never ship to clients** — clients talk to your backend, and only
  the backend talks to databases, payment rails, and model providers; any
  credential embedded in a distributed app will eventually leak.
- **Tier taxonomy as a complexity dial** — 1-tier (everything local, single
  user), 2-tier (client straight to a database, viable only in controlled
  internal settings), 3-tier (presentation / application / data — the default
  baseline for web and mobile), N-tier (gateways, auth services, caches,
  queues, model services added only when scale, compliance, or team ownership
  justify them).
- **Stateless app servers as the first scaling move** — keep user state out of
  server-local memory (push sessions to a shared store) so any replica behind
  the load balancer can serve the next request, enabling horizontal scale and
  clean failover.
- **Cache before you add servers** — CDN for static assets near users, an
  application cache for hot reads; skipping repeated work is usually cheaper
  than buying more compute.
- **Database bottleneck escalation ladder** — indexes and query tuning first,
  then read replicas, pooling, and partitioning; sharding last because of its
  complexity cost.
- **Move slow work off the request path** — emails, media processing, reports,
  and long AI workflows go to queues and background workers; accept, persist,
  respond fast, finish asynchronously.
- **Self-protection under load** — rate limiting, backpressure (accept less),
  load shedding (drop low-priority work), and graceful degradation (keep the
  critical features alive) instead of trying to serve everything and dying.
- **Designed-for-failure client-server calls** — timeouts, retries with
  backoff, health checks, failover, and idempotency keys so a retried request
  is not executed twice; the goal is containment, not prevention.
- **Version for the client you shipped months ago** — old app versions keep
  calling; evolve APIs backward-compatibly or with explicit versions and
  gradual migrations.
- **Split services only when the boundary is clear and the pain is real** —
  premature decomposition buys network hops, deployments, and failure modes
  before it buys anything else.
- **Cost as a design input** — servers, DB calls, model calls, logging, and
  cross-region traffic are all billable; account for them at design time, not
  at invoice time.

## When to apply / trade-offs

This is the baseline mental model for any hosted product; the tier taxonomy is
a useful vocabulary for deciding how much architecture a project deserves
(defaulting to 3-tier and adding layers reluctantly). The article is honest
about the pattern's central weakness: the same centralization that creates a
trusted enforcement point also concentrates risk — one overloaded database,
region, or third-party dependency becomes the bottleneck or single point of
failure, and every network hop adds latency bounded by the slowest important
step. Its modern framing (a streaming AI chat backend as a worked example)
shows "the server" is now typically a fleet of cooperating services, which
raises the observability bar. Educational-platform content, so breadth over
depth, but no vendor pitch.

## Fidelity check

1. Claim: the article grounds server-side enforcement in client
   untrustworthiness. Support: the capture states clients may run stale
   versions, alter local data, or forge requests, and that only the server can
   reliably block an action the UI merely hides.
2. Claim: statelessness is presented as the prerequisite for the first scaling
   move. Support: the capture defines stateless as keeping no essential
   user-specific data solely in a server's local memory, and says systems move
   session state to a shared store so any healthy replica can take the next
   request behind the load balancer.
3. Claim: it recommends idempotency keys as part of failure handling. Support:
   the capture describes request IDs that let a server process a retried
   request safely without repeating the work, listed alongside timeouts,
   backoff retries, and failover.
