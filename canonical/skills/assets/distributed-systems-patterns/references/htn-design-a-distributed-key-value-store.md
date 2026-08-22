# Digest: Design a Distributed Key-Value Store

- **Source:** https://x.com/Harry_The_Nerd/status/2047329176982827353
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level system design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

The article walks through the standard building blocks of a Dynamo/Cassandra-style
distributed KV store: how keys find machines, how data survives crashes, how
consistency is tuned, and what each node runs locally.

## Patterns

### Consistent hashing for key placement

Servers and keys are both hashed onto a circular keyspace; a key is owned by the
first server encountered moving clockwise from the key's position. Lookup is a
constant-time hash + ring walk, so any coordinator can locate the owner of a key
without a central directory. The decisive property: when one of N servers joins or
leaves, only roughly 1/N of keys change owners instead of a full rehash of the
dataset. Use it whenever data must be partitioned across a fleet that changes size;
the trade-off is added ring-management machinery (and, in real systems, virtual
nodes for balance — not covered by the article). The author notes Cassandra and
Redis Cluster both rely on this scheme.

### Proactive write-time replication

Rather than copying data after a machine dies, every write is sent to the key's
primary owner plus additional replicas at the moment it happens. The article uses
the common production setting of replication factor 3 (one primary, two replicas),
so the loss of the primary leaves two live copies with no recovery scramble.
Trade-off: 3x storage and extra write fan-out in exchange for durability and
read availability during failures.

### CAP positioning via quorum tuning (N, W, R)

Since partitions are unavoidable, the practical design choice is consistency
versus availability, and quorum parameters make that choice per workload:
N is the replica count, W the number of acknowledgements required for a write,
R the number of replicas consulted on a read. When W + R exceeds N, read and
write sets must overlap, giving strong consistency. The article's worked examples:
a money transfer wants something like W=3/R=2 (consistent, CP-leaning), while a
social-media like counter is fine at W=1/R=1 (fast and available, AP-leaning,
tolerating staleness). The engineering skill is matching the knob setting to the
data's actual correctness requirement rather than picking one mode globally.

### Vector clocks for concurrent-write detection

Physical timestamps cannot order writes across machines because clocks drift.
Instead each replica keeps a per-node logical counter; a version like {A:2}
provably descends from {A:1} and wins, whereas {A:1} and {B:1} are incomparable
— a true concurrent conflict that must be surfaced rather than silently ordered.
Resolution options once a conflict is detected: last-write-wins (simplest, risks
dropping an update), semantic merge (fits commutative data such as counters or
shopping carts), or returning both versions to the client so the application
decides — the approach the article attributes to Amazon's cart.

### Gossip-based failure detection

A central health-checker pinging thousands of nodes is both a bottleneck and a
single point of failure. In gossip, each node periodically swaps membership and
health state with a small random sample of peers, so knowledge of a dead node
propagates cluster-wide in seconds without any coordinator. The article describes
a two-stage state machine: about 10 seconds of silence marks a node suspected,
about 30 seconds confirms it dead and triggers key rerouting. It cites Cassandra's
cadence of gossiping with 3 random peers once per second.

### LSM tree as the per-node storage engine

The store is itself the database — nodes do not delegate persistence to another
DBMS. Each node uses a log-structured merge tree: writes land in an in-memory
MemTable; when it fills, it is flushed as an immutable on-disk SSTable; background
compaction periodically merges SSTables so read amplification stays bounded.
This layout optimizes for write throughput (memory-speed ingest, sequential disk
flushes) at the cost of compaction work and multi-file reads — the standard
choice for write-heavy KV workloads.

### Write-ahead log for crash durability

Because the MemTable is volatile, every mutation is first appended to a sequential
on-disk log before being applied in memory. After a crash, the node replays the
log to reconstruct the MemTable, so acknowledged writes survive even a hard power
loss. Appending to a log is a sequential disk operation, so the durability step
adds minimal latency compared to random-access writes.

### External coordination service (Zookeeper)

Cluster-wide metadata — the ring mapping, replication factor, quorum settings,
and the membership list — lives in a dedicated coordination service that all
nodes watch for changes. Failure information discovered via gossip is fed back
into it so the routing state stays current and coordinators stop sending traffic
to dead nodes. Trade-off (implicit): you gain a consistent source of truth for
config at the price of operating one more critical system.

### Non-functional properties as consequences of the above

The article closes by deriving the "-ilities" from the mechanisms: scalability
comes from adding ring nodes with only the affected key ranges moving; latency
comes from memory-first writes (microsecond-scale), sequential-only WAL I/O, and
reads that query R replicas in parallel and take the first valid answer;
availability comes from RF=3 tolerating two simultaneous node losses without
data loss, with gossip + coordination-service updates rerouting around failures
automatically. Useful as a template for arguing NFRs from mechanisms rather than
asserting them.

## Not absorbed

- Series branding ("High-Level Design Questions-Based Series #7") — content-marketing framing, not engineering.
- The remark that knowing which quorum setting to pick is "the interview answer" — interview-prep framing; the underlying CP/AP reasoning is absorbed above.
- "The full architecture" section — heading only in the capture, almost certainly an image the text render could not carry; no textual substance to absorb.
- Post metadata (timestamp, view/like counts) — engagement telemetry, not content.

## Fidelity check

- **Post count in capture:** 1 (a single long-form article post; no thread).
- **Article outline (author's own ordering):**
  1. Intro — the "giant HashMap across machines" framing; Redis/Cassandra/DynamoDB as examples
  2. Functional requirements — put/get/delete, replication, distribution
  3. Distributing data — consistent hashing
  4. Surviving failures — replication
  5. Consistency vs availability — CAP and quorum
  6. Resolving conflicts — vector clocks
  7. Detecting failures — gossip protocol
  8. The data layer — LSM Tree (local storage on each node)
  9. Write-Ahead Log (WAL)
  10. Zookeeper — config and coordination
  11. The full architecture (heading only; likely a diagram)
  12. Non-functional requirements — Scalability, Latency, Availability
- **Pattern-to-section citations:**
  - Consistent hashing for key placement → section 3 ("Distributing data - consistent hashing")
  - Proactive write-time replication → section 4 ("Surviving failures - replication")
  - CAP positioning via quorum tuning → section 5 ("Consistency vs availability - CAP and quorum")
  - Vector clocks for concurrent-write detection → section 6 ("Resolving conflicts - vector clocks")
  - Gossip-based failure detection → section 7 ("Detecting failures - gossip protocol")
  - LSM tree as the per-node storage engine → section 8 ("LSM Tree - local storage on each node")
  - Write-ahead log for crash durability → section 9 ("Write-Ahead Log (WAL)")
  - External coordination service (Zookeeper) → section 10 ("Zookeeper - config and coordination")
  - Non-functional properties as consequences → section 12 ("Non-functional requirements")
