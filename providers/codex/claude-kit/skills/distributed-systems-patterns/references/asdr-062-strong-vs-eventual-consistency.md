---
source: https://blog.algomaster.io/p/strong-vs-eventual-consistency
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Consistency models for replicated data: strong vs eventual

## What it teaches

On one server, a read after a write trivially returns the new value. Once
data is replicated across nodes and regions, an update to one replica takes
time to reach the others, and during that lag replicas disagree. A
consistency model is the contract answering: after I write, when, where, and
in what order do others see it? **Strong consistency** promises every read —
anywhere — reflects the latest committed write, as though one global copy
existed; it achieves this by making the write path wait for replica
acknowledgment, coordinated via consensus protocols (Paxos/Raft family).
**Eventual consistency** acknowledges the write at one node immediately and
propagates asynchronously; replicas converge on the same value once writes
stop, but until then reads may be stale. The article also maps the useful
middle ground: client-centric guarantees that soften eventual consistency's
rough edges.

## Key patterns & decisions

- **Acknowledge-after-replication vs acknowledge-then-replicate**: strong
  consistency confirms a write only after enough replicas apply it; eventual
  consistency confirms instantly and syncs in the background — this single
  ordering choice drives the entire latency/availability/correctness split.
- **Consensus protocols underpin strong ordering**: agreement algorithms
  give all replicas one shared operation order, which is what makes the
  "single global copy" illusion hold.
- **CAP-driven availability sacrifice**: under a network partition, a
  strongly consistent system may refuse requests to avoid serving divergent
  data; an eventually consistent one keeps answering.
- **Conflict resolution is mandatory once replicas accept concurrent
  writes**: last-write-wins, CRDTs, or application-semantic merge logic —
  pick one before conflicts happen, not after.
- **Client-centric consistency ladder**: causal consistency (effects never
  appear before their causes — a reply never precedes its parent comment),
  read-your-writes (an author always sees their own update), monotonic reads
  (a client never observes values going backward in time), monotonic writes
  (one client's writes apply in issue order). These bolt user-facing sanity
  onto an eventually consistent core.
- **UX techniques absorb staleness**: optimistic UI updates and explicit
  syncing indicators let products tolerate propagation lag without confusing
  users.
- **Data-criticality triage**: money, stock levels, exclusive locks, and
  unique ID issuance demand strong guarantees; counters, analytics,
  recommendations, DNS, and CDN assets tolerate lag.

## When to apply / trade-offs

- Strong consistency buys simple application code (no stale-read handling,
  no merge logic) and predictable reads, paying with coordination latency —
  worst across regions — reduced availability during partitions, and
  heavier infrastructure.
- Eventual consistency buys fast writes, partition-tolerant availability,
  and easy geo-scale (especially read-heavy), paying with temporary
  staleness, conflict-resolution machinery, and complexity pushed into
  application code (idempotency, read-after-write workarounds).
- A seven-factor rubric guides the call: data criticality, user tolerance
  for staleness (and UX mitigation), latency budget, availability
  requirements under partition, scalability ambitions, developer complexity
  appetite, and the concurrent-write conflict story.
- Shopping carts are an instructive edge case: cross-device cart merges are
  handled acceptably with eventual consistency plus merge/LWW strategies,
  even though checkout-adjacent inventory needs strong guarantees.

## Fidelity check

1. Claim: strong consistency's write path blocks on replica acknowledgment.
   Support: the capture's mechanics describe the primary propagating the
   write to replicas, each replica acknowledging, and the client's write
   confirming only after all-or-enough acknowledgments, with Paxos and Raft
   named as the coordinating protocols.
2. Claim: eventual consistency only guarantees convergence in the absence of
   new writes. Support: the capture defines the model as all replicas
   converging to the same value eventually provided updates stop, with no
   bound on how quickly convergence occurs.
3. Claim: client-centric models add order guarantees without full strong
   consistency. Support: the capture enumerates causal, read-your-writes,
   monotonic-reads, and monotonic-writes variants — e.g. a like counter that
   may lag but never decreases for the same observer, and a user's refreshed
   profile always showing their own just-saved edit.
