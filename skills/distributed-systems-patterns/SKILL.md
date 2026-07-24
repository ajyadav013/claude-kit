---
name: distributed-systems-patterns
description: Distributed data placement and replication — consistent hashing/vnodes, sharding, N/W/R quorums, KV-store and cache anatomy, gossip failure detection, B-tree vs LSM engines. Use when designing a sharded, replicated, or cached data tier.
---

Design and review distributed data tiers — how keys find nodes, how data survives node loss, how consistency is tuned per workload, and what storage engine each node runs under the hood.

## When to use

- Designing or reviewing data placement for a horizontally scaled store (distributed cache, KV store, sharded database)
- Choosing a partitioning scheme (hash vs range vs directory) or diagnosing a hot partition
- Deciding whether to shard at all — climbing the scaling ladder in the right order
- Tuning replication and quorums (N/W/R) to a workload's actual correctness requirement instead of one global mode
- Debugging stale reads caused by replication lag (read-your-writes violations after a write)
- Designing a distributed cache cluster: placement, write strategy, eviction, invalidation, hot keys, herd protection
- Adding failure detection and membership (heartbeats, gossip) to a clustered service
- Choosing between B-tree and LSM storage for a read-heavy vs write-heavy workload
- Weighing cross-shard atomicity options (two-phase commit vs sagas) after a sharding decision
- Relieving a read or throughput bottleneck with materialized views or batching before reaching for a reshard
- Explaining why adding or removing one node reshuffled keys, wiped a cache tier, or overloaded a neighbor

Scope boundary — this skill owns **data placement and replication mechanics**. Adjacent territory is owned elsewhere:

- The partition trade-off itself (CAP/PACELC), clock/ordering correctness, retries, circuit breakers, and backpressure belong to `.claude/rules/resilience-engineering.md` (always loaded) — sections below point there instead of restating it.
- System-scale composition (gateways, queues, fan-out, rate limiting) belongs to the `system-design-patterns` skill.
- Concrete cache implementation in a running service belongs to `redis-caching-patterns`; single-node transactions and locking belong to `python-dao-and-database`.

## Consistent hashing

1. **Know why the obvious scheme fails before replacing it.** `hash(key) mod N` routes a key to one of N nodes with no lookup table and no coordination — every client computes the owner independently, in constant time. Its hidden assumption is that N never changes. It is acceptable only when membership is genuinely fixed or remapping is free (stateless routing).

2. **The mod-N reshuffle is a cluster wipe.** The moment a node joins or dies, the modulo arithmetic reassigns roughly (N−1)/N of all keys — almost the entire keyspace changes owner in one instant. For a cache tier that is equivalent to flushing the cluster: every request misses simultaneously and falls through to the database, and the resulting cold-cache stampede can cascade into a full outage. Any placement scheme that bakes the cluster size into the hash turns node failure — an inevitable event — into a remap-everything event. Design for membership churn as a normal operation, not an exception.

3. **The ring.** Consistent hashing maps servers and keys into the same circular hash space (conceptually 0 to 2^32−1, wrapping around). Each server hashes an identifier (hostname/IP/ID) to a ring position; each key hashes to its own position; a key's owner is the first server encountered walking clockwise.

    ```
            0/2^32
              |
        S3 ---+--- k1 → owner: S1 (first server clockwise)
       /              \
      k4               S1
      |                 |
      S2 ------ k3 ---- k2 → owner: S2
                (k3 → owner: S2)
    ```

    Implement lookup as a sorted array (or balanced tree) of server positions plus a binary search for the first position ≥ hash(key), wrapping to the smallest position past the top — O(log N) per lookup, no central directory.

4. **Bounded key movement is the whole point.** Adding a server claims only the arc between it and its counterclockwise predecessor; removing a server hands its arc to the next clockwise node. With K keys on N servers, a membership change moves roughly K/N keys — every other node is untouched. Compare that to the near-total remap of mod-N: this property is what makes scale-out and failure recovery routine operations instead of incidents.

5. **The basic ring has three predictable defects.** Server positions come from hashing a handful of names, so with few points on the circle:
    - **Uneven arcs** — one node can own half the ring while another owns a sliver; load is wildly unbalanced.
    - **Neighbor-dump on failure** — a dead node hands its *entire* arc to exactly one clockwise neighbor, which can overload that neighbor and start a domino of failures.
    - **No capacity weighting** — there is no way to give a bigger machine a bigger share.

    These are geometric consequences of placing few points on a ring, not rare edge cases.

6. **Virtual nodes fix all three.** Place each physical server on the ring many times by hashing derived identifiers (`node-a#1`, `node-a#2`, …); 100–200 vnodes per physical machine is a common operating point. Each machine then owns many small scattered arcs whose sizes average out:
    - **Even load** — aggregate ownership per machine converges to near-equal shares even in small clusters.
    - **Graceful failure** — a dead node's ~150 scattered arcs are absorbed by many different physical neighbors, spreading its load thin instead of doubling one victim's traffic.
    - **Smooth scale-out** — a joining node takes small slices from many existing nodes rather than one big arc from a single neighbor.
    - **Capacity weighting for free** — give a machine with twice the RAM/CPU twice the vnodes and it attracts roughly twice the keys; no separate weighting logic needed.

7. **Tune the vnode count, don't max it.** The ring's position index grows by the vnode multiplier — more entries to binary-search and more membership metadata to keep in sync across the cluster. That is why vnode counts are an operating point to tune, not a number to crank arbitrarily high.

8. **Where the pattern shows up.** Cassandra's token ring (vnodes included) and DynamoDB's partitioning are direct implementations; CDNs route requests to edge nodes this way with no central lookup table; load balancers use it so sticky sessions survive backend scale-up/down with only the affected arcs remapping. The progression mod-N → basic ring → vnodes is worth internalizing as a method: each design is adequate until scale breaks one of its assumptions, and the successor targets exactly that failure mode.

## Partitioning and sharding

1. **Climb the scaling ladder in order — sharding is the last rung.** A single primary with good indexes and query discipline carries far more traffic than intuition suggests. Exhaust the cheaper rungs first:

    | Rung | Move | What it buys |
    |------|------|--------------|
    | 1 | Optimize the single node | Indexes, query shape, pooling — often 10× for free |
    | 2 | Cache the hot read set | Absorbs the read multiplier before it reaches the DB |
    | 3 | Add read replicas | Horizontal read scale; primary handles writes only |
    | 4 | Scale vertically | A bigger box is operationally free vs resharding |
    | 5 | Shard | Only when write volume or working set exceeds all of the above |

    The classic era of URL shorteners and early social platforms served enormous traffic for years on rungs 2–3 alone. Sharding buys write scale at the permanent price of losing cross-shard transactions and joins, complicating every operational procedure, and making key-distribution mistakes expensive — take that deal only when forced.

2. **Read replicas: the workhorse of rung 3.** One primary handles all mutations; asynchronous replication fans data out to replicas that serve selects, search, reporting, and analytics. Read-heavy products (feeds, profiles, content platforms, public APIs) scale a long way on this rung. Two costs come with it: replication lag means read-your-writes is not guaranteed (see point 5), and primary failover/promotion is the operationally hard part — rehearse it before you rely on it.

3. **Three ways to split, with distinct failure modes:**

    | Scheme | How | Strength | Weakness |
    |--------|-----|----------|----------|
    | Hash | Route by hash of partition key | Even key spread | Destroys range scans; adjacent keys scatter |
    | Range | Each shard owns a contiguous key range | Cheap range scans, ordered access | Sequential keys hammer the tail shard |
    | Directory | Lookup service maps key → shard | Surgical placement and rebalancing | One more critical, consistent, HA component on every request path |

    Hash sharding should be combined with consistent hashing so membership churn moves only ~1/N of keys. Range sharding on timestamps or auto-increment IDs aims every insert at the newest shard — a hot partition by construction. Directory sharding is the flexible option for tenant-level placement, but the directory's availability now bounds the whole tier's availability.

4. **Hot partitions come from key choice, not bad luck.** A celebrity user, a monotonic key, or a coarse partition key (partition-by-country puts one populous country on one shard) concentrates traffic while other shards idle. Defenses:
    - Pick higher-cardinality, traffic-uniform partition keys in the first place.
    - Salt or split known-hot keys across sub-partitions and merge on read.
    - Isolate whale tenants onto dedicated partitions rather than letting them degrade shared ones.
    - Watch per-partition metrics, not per-cluster averages — a healthy mean hides a burning shard.

5. **Replication lag is a product decision, not a footnote.** With async replicas, a user can write to the primary and immediately read stale data from a replica — the "my edit disappeared" bug. Route lag-sensitive reads (a user reading back their own just-written data) to the primary, or to a replica whose reported replication position has passed the client's write; let analytics and search tolerate staleness on any replica. Name the guarantee explicitly ("your own writes are visible immediately; others' writes within X seconds") instead of letting it emerge by accident.

6. **Materialized views are a read-scaling lever that often postpones sharding.** When the read bottleneck is an expensive aggregation (dashboards, reports, recommendation summaries) rather than raw row lookups, precompute the query result into its own table and serve reads from that. Three refresh strategies, by staleness budget:
    - **Scheduled** — recompute every N minutes/hours; simplest, staleness bounded by the interval.
    - **Incremental** — recompute only the deltas since the last refresh; cheaper at scale.
    - **Event-driven** — update the view when a relevant write occurs; freshest, most machinery.

    The trade is explicit staleness plus refresh orchestration in exchange for reads that no longer touch the expensive query path. A creator dashboard aggregating views and watch-time periodically — instead of live per page load — is the canonical shape.

7. **Know the cross-shard atomicity cost before you shard.** Once related rows live on different shards, "both updates apply or neither" needs a protocol. Two-phase commit is the classic one: a coordinator asks every participant to *prepare* (validate, lock resources, vote), and only a unanimous yes triggers the global *commit* — any no triggers global rollback. It delivers real atomicity, and its costs are exactly why modern systems avoid it: participants sit blocked holding locks while the protocol runs, the coordinator is both a bottleneck and a single point of failure, latency stacks with participant count, and partial-failure recovery is genuinely messy. Reserve 2PC for the narrow cases where partial success is unacceptable (the debit-and-credit pair of a funds transfer); prefer sagas, event-driven flows, and compensating transactions everywhere else — and let this cost push you back up the scaling ladder: data that transacts together should live on one shard in the first place.

## Replication and quorum

1. **Replicate at write time, not at failure time.** Copying data after a machine dies is a recovery scramble racing the next failure. Instead, every write is sent to the key's primary owner plus its replicas *at the moment it happens* — a replication factor of 3 (one primary, two replicas) is the standard production setting, so losing the primary leaves two live copies and no emergency. The cost is 3× storage and write fan-out, paid deliberately for durability and read availability during failures.

2. **Choose a topology: leader-follower or leaderless.**
    - **Leader-follower** — one node orders all writes for a partition; followers replay its stream. Simple to reason about, and read-your-writes is solvable by reading the leader. Costs: failover/promotion is a real operational event, and the leader caps write throughput for its partition. The right default for transactional stores.
    - **Leaderless (Dynamo-style)** — any replica accepts writes; quorums reconcile divergence. No failover event and better write availability under node loss, but concurrent writes now genuinely conflict, and the system needs the conflict machinery in the KV-store section below. Suits high-availability KV workloads.

3. **N/W/R — the consistency knob, tuned per workload.** In a quorum system: N is the replica count, W how many replicas must acknowledge a write, R how many are consulted on a read. When **W + R > N**, every read set overlaps every write set in at least one replica, so a read is guaranteed to see the latest acknowledged write — read-your-writes by arithmetic, no timestamps involved.

    ```
    N=3, W=2, R=2:
    replicas:   [R1]   [R2]   [R3]
    write set:  {R1, R2}          — acked by 2 of 3
    read set:          {R2, R3}   — queries 2 of 3
    overlap:            R2        — guaranteed, because 2+2 > 3
    ```

    | Workload | Setting (N=3) | Leaning |
    |----------|---------------|---------|
    | Funds transfer, inventory decrement | W=3, R=2 (or W=2, R=2) | Consistency — overlap guaranteed |
    | Like counter, view counter, presence | W=1, R=1 | Availability/latency — staleness tolerated |
    | Balanced default | W=2, R=2 | Overlap, with tolerance for one slow node |

4. **Match the knobs to the data's actual correctness requirement, not one global mode.** The engineering skill is recognizing that the funds transfer and the like counter in the same system deserve different settings. Which side of the partition trade-off a workload should sit on — and the vocabulary for making that call (CAP, PACELC) — is owned by `.claude/rules/resilience-engineering.md`; this section supplies the mechanism that implements the choice, not the decision framework.

5. **Raising W costs write latency; raising R costs read latency.** W=N means every write waits for the slowest replica and fails if any replica is down; W=1 acknowledges after one copy and risks serving a stale read from the others unless R compensates. Reads can hedge: query R replicas in parallel and take the first valid quorum of answers, so one slow replica doesn't set the latency floor.

6. **Lag-aware read routing for async topologies.** Quorum overlap covers the leaderless path; leader-follower systems with async followers instead need routing discipline: session-sticky reads to the leader after a recent write, or followers that report replication position so the router can exclude any replica behind the client's last write. Either mechanism turns "eventual" into a named, testable guarantee.

## Anatomy of a distributed KV store

The Dynamo/Cassandra lineage combines the pieces above into a standard machine. Knowing the anatomy lets you evaluate any store's documentation quickly — each mechanism exists to answer one specific failure.

1. **Coordinator and preference list.** Any node can accept a request; the receiving node acts as *coordinator*, hashes the key, and forwards the operation to the key's *preference list* — the first N distinct physical nodes encountered clockwise on the ring (skipping vnodes that map back to an already-listed machine). There is no central router in the data path.

2. **External coordination service for cluster metadata.** The ring mapping, replication factor, quorum settings, and membership list live in a small dedicated coordination service that all nodes watch for changes. Failure information discovered by gossip feeds back into it so coordinators stop routing to dead nodes. The trade-off is explicit: a consistent source of truth for cluster config, at the price of operating one more critical system.

3. **Hinted handoff — write availability through short outages.** If a preference-list node is down at write time, the coordinator writes that copy to the *next* healthy node with a hint naming the intended owner. When the owner returns, the hint-holder hands the data over and deletes its copy. Writes stay available through transient failures without silently reducing the replica count.

4. **Read repair — healing staleness on the read path.** When a quorum read fans out to R replicas and the responses disagree, the coordinator returns the newest version to the client and, in the background, writes that version back to the stale replicas. Frequently read data converges automatically, with no separate process.

5. **Anti-entropy with Merkle trees — healing staleness nobody reads.** Read repair only fixes what gets read. A background anti-entropy process periodically compares replicas' key ranges using Merkle trees (hash trees over the data): if two replicas' root hashes match, the entire range is identical and the comparison cost one hash exchange; if they differ, descend only into the differing subtrees to locate and sync divergent keys. This makes continuous full-replica comparison affordable.

6. **Conflict resolution — vector clocks, or last-write-wins with eyes open.** Wall-clock timestamps cannot order writes across machines — clocks drift; the distributed-time correctness rules live in `.claude/rules/resilience-engineering.md` (section 2). Vector clocks give causal ordering instead: each replica keeps a per-node logical counter, so version `{A:2}` provably descends from `{A:1}` and supersedes it, while `{A:1}` and `{B:1}` are incomparable — a true concurrent conflict that must be *surfaced*, not silently ordered. Resolution options, in increasing effort:
    - **Last-write-wins** — simplest; silently drops one of the concurrent updates. Acceptable only where losing an update is genuinely fine.
    - **Semantic merge** — natural for commutative data: counters, sets, shopping carts.
    - **Return both siblings** — hand the conflict to the application to reconcile; the classic shopping-cart approach.

    Choosing LWW is choosing data loss under concurrency — make that choice explicitly per dataset, never by default.

7. **Walk the write path end to end.** Every box in this flow maps to one mechanism above; a design review that can't walk the path has found its gap.

    ```
    write: client → any node (coordinator) → hash key to ring position
           → forward to preference list (N replicas)
           → each replica: append WAL → apply to memtable → ack
           → coordinator responds after W acks
           → hinted handoff covers any replica that is down
    ```

8. **And the read path.** The same flow in reverse is where staleness gets caught and healed:

    ```
    read:  client → coordinator → preference list (R replicas queried)
           → collect responses, compare versions
           → newest version → client
           → background: read-repair any replica that answered stale
    ```

9. **Derive the -ilities from the mechanisms, don't assert them.** Scalability: add ring nodes; only the affected arcs move. Latency: memory-first writes, sequential-only WAL I/O, reads querying R replicas in parallel and taking the first valid answers. Availability: RF=3 tolerates two simultaneous node losses; gossip plus coordination-service updates reroute around failures automatically. Arguing non-functional requirements as consequences of mechanisms is the template — for your own designs and for evaluating others'.

## Distributed cache design

1. **A cache is a speed layer, never a store of record.** Every cached entry is an expiring RAM copy of something durable elsewhere; losing the entire cache tier costs latency, never data. This framing does real work:
    - It decides what belongs in the cache — recomputable or refetchable hot reads.
    - It keeps node-failure handling simple — fall through to the database: slower, still correct.
    - It makes cold start an accepted warm-up period (each miss repopulates from the DB) rather than a problem to engineer away with persistence machinery.

    If losing a cache node would lose data, the design has quietly become a KV store without a KV store's durability machinery — see the anatomy section above for what that actually requires.

2. **Keep the functional contract narrow.** Put with TTL, get returning value-or-miss, eviction under memory pressure, invalidation when the origin changes, and a defined miss path (read DB → populate → return). A narrow contract is what lets every node stay independent and the tier scale horizontally with no cross-node coordination on the hot path.

3. **Placement is consistent hashing again.** Cache nodes sit on a hash ring; keys route clockwise; adding or removing a node remaps ~1/N of the keyspace instead of wiping the tier. The mod-N cold-cache stampede from the first section is *the* canonical cache-cluster outage — the placement scheme is the first thing to check in any cache design review.

4. **Write strategy — one heuristic, three options:**
    - **Cache-aside (lazy loading)** — the application owns population: on a miss it reads the DB and writes the result into the cache itself. Memory is spent only on keys actually requested. Costs: first read of any key pays full DB latency, and a cache outage sends the entire read load to the DB. Default for read-heavy workloads.
    - **Write-through** — every write lands in cache and DB together, acknowledged only when both confirm. The cache can never serve stale data because it updates in the same operation as the origin. Costs: dual-write latency on every write, and the cache accumulates entries nobody may read. Fits write-heavy data where consistency outranks write speed.
    - **Write-behind (write-back)** — writes hit only the cache and acknowledge immediately; a background flusher batches them to the DB, which then never sees per-request write traffic. Fastest write path and excellent burst absorption, but a node crash between acknowledgment and flush *permanently loses those writes*, consistency is only eventual, and the flush path needs real retry/recovery machinery. Reserve for high-frequency loss-tolerant streams: view counters, impressions, analytics events — never money.

    Rule of thumb: read-heavy → cache-aside; write-heavy + consistency → write-through; write-heavy + raw speed and loss tolerance → write-behind.

5. **Eviction: recency vs frequency.** When a node's RAM fills, what gets discarded should match the workload's access shape:
    - **LRU** evicts the entry idle the longest — right when access is recency-dominated: sessions, feeds, recent searches.
    - **LFU** evicts the entry with the lowest lifetime access count — right when access is popularity-dominated (top content), since a globally popular item survives a quiet hour that would evict it under LRU.
    - **The production hybrid** pairs LFU-style eviction with TTL expiry: frequency decides what stays under memory pressure, while TTL clears historically popular but now-stale entries.

6. **Invalidation: three strategies, chosen by staleness budget.**
    - **TTL expiry** — attach a lifetime; staleness resolves itself when the timer fires. Zero coordination, bounded stale window. Fine for non-critical data.
    - **Event-driven** — on a DB change, publish a change event on a message bus; a cache-side consumer deletes the affected key, so the next read repopulates fresh. Near-zero staleness at the cost of operating an event pipeline. The choice for correctness-critical data.
    - **Version tagging** — each cached entry carries a version mirroring a version column in the DB; a read compares the two and treats mismatch as a miss. Precise per-read freshness, but requires schema support and a comparison on the read path.

7. **Hot keys break per-node math.** Consistent hashing spreads *keys* evenly, not *traffic* — one viral key routes its entire load to a single node. Mitigations:
    - Replicate the hot key across several nodes (e.g., suffix the key with a small random index on write, fan the suffixes on read) so its traffic spreads.
    - Add a short-TTL local cache inside the application in front of the distributed tier for the hottest handful of keys.
    - Detect hotness from per-key metrics before it becomes an incident; per-node averages hide it.

8. **Thundering herd at cluster scale.** When a hot entry expires — or a node restarts, or clients reconnect en masse — every concurrent reader misses at once and stampedes the database with identical queries, spiking CPU and latency in lockstep with the TTL. Layered defenses:
    - **Request coalescing** — one in-flight rebuild per key; everyone else waits on it.
    - **A distributed lock** — exactly one process recomputes; others retry the read briefly or serve the last good value.
    - **Jittered TTLs** — randomize lifetimes so entries don't expire in synchronized waves.
    - **Stale-while-revalidate** — keep serving the old value while a background refresh runs.

    Rate limiting as the downstream backstop is owned by `.claude/rules/resilience-engineering.md`. Single-node lock mechanics and probabilistic early expiration are covered concretely in `redis-caching-patterns` (convention 14).

9. **Keep the planes separate.** Data plane: per-node RAM holding key, value, TTL, version. Control plane: a coordination service holding ring configuration, node-health state fed by gossip, and cluster policy defaults (eviction policy, default TTL, per-node size limits). Event plane: the message bus carrying invalidation events from the DB to cache consumers. Cluster metadata and data payloads travel through entirely separate systems; a design where the data path depends on the control path on every request has a hidden availability coupling.

10. **The failure flow is the design's proof.** If you cannot narrate this flow for a proposed design, the design is not finished:

    ```
    read:   client → app → ring routing → owning node → hit (microseconds)
            miss → DB fetch → populate with TTL → return

    node
    failure: gossip detects within seconds → coordination layer updates ring
             → traffic reroutes to new owners
             → interim reads fall through to the DB — degraded, not down
    ```

## Failure detection and gossip

1. **A central health-checker doesn't scale and is its own single point of failure.** One process pinging thousands of nodes is a bottleneck, and when *it* dies the cluster goes blind. Failure detection should be as decentralized as the data it protects.

2. **Gossip dissemination.** Each node periodically exchanges its view of membership and health with a small random sample of peers — Cassandra's cadence is 3 random peers once per second. Information spreads epidemically: knowledge of a dead node reaches the whole cluster in seconds, per-node cost stays constant as the cluster grows, and there is no coordinator anywhere. The same channel carries joins and leaves; what gossip learns feeds the coordination service so routing state stays current.

3. **Suspect before you convict.** Declaring a node dead on one missed heartbeat causes flapping under GC pauses and network blips; waiting too long delays recovery. The two-stage discipline: roughly 10 seconds of silence marks a node *suspected*; roughly 30 seconds confirms it *dead* and triggers rerouting of its keys. Suspected nodes can be deprioritized for reads before the cluster commits to expensive ownership changes.

4. **Phi-accrual, in plain terms.** Fixed timeouts encode one guess about network behavior. The phi-accrual approach replaces the binary "dead after T seconds" with a continuously rising suspicion score: track the historical distribution of each peer's heartbeat inter-arrival times and compute, for the current silence, "given this node's history, how improbable is a heartbeat this late?" Consumers act at different thresholds — reroute reads at mild suspicion, trigger expensive recovery only at near-certainty — and the detector self-tunes per link, so a node on a flaky WAN link isn't judged by LAN expectations.

5. **Split-brain awareness.** A network partition makes each side see the other as dead — both may elect leaders, claim shard ownership, and accept conflicting writes. Two disciplines keep this survivable:
    - Authoritative membership decisions (leader election, shard ownership changes) require a **majority quorum**, so at most one side of a partition can proceed.
    - Data written on both sides of a healed partition must flow through the conflict-resolution machinery above (vector clocks, semantic merge, surfaced siblings) rather than being silently clobbered.

    How a service should *behave* during the partition — degrade, refuse, or serve stale — is the partition-behavior decision owned by `.claude/rules/resilience-engineering.md`.

## Storage engines under the hood

Distributed stores are local storage engines glued together by everything above — and engines differ from one another almost entirely in the storage layer, where hardware costs (seek latency, page size, cache locality) collide with software. Two families dominate; picking between them is a read/write-profile decision, not a fashion choice.

1. **The page abstraction drives everything.** Disks and SSDs transfer fixed-size pages (4–16KB), and reading one byte of a page costs about the same as reading the whole page. The right cost metric for any on-disk structure is **pages read, not comparisons made**.

2. **Why binary search trees fail on disk.** A BST's O(log₂ n) assumes uniform access cost — true in RAM, false on disk. A million-entry binary tree is ~20 levels deep; with tiny nodes scattered across the disk, one lookup can cost up to 20 random page reads, potentially milliseconds each. The fix is trading depth for width: make each node fill a page (~100 keys, ~101 children) and the same million keys need ~3 levels.

3. **B+trees — the read-optimized default.** Page-sized nodes of sorted keys; all leaves at identical depth, so lookup cost is uniform and predictable. Internal nodes carry only routing keys — maximizing fanout and flattening the tree — while leaves hold the data (or row pointers) and are chained in sorted order, so a range query descends once and then walks leaves sequentially. Why this family won for OLTP:
    - Huge fanout keeps billion-row datasets at 3–4 levels; the small upper levels stay cached, so real lookups often cost 1–2 physical reads.
    - Splits and merges keep the tree balanced by construction — no degenerate cases.
    - Linked leaves make the very common range/ORDER BY shapes cheap.
    - In-place updates keep read latency predictable, and five decades of maturity mean concurrency, recovery, and bulk loading are solved problems.

4. **LSM trees — the write-optimized inversion.** Writes land in an in-memory sorted **memtable** — zero disk I/O on the hot path. Because the memtable is volatile, every mutation is first appended to a **write-ahead log**: a sequential disk append costing minimal latency, replayed after a crash so no acknowledged write is lost. When the memtable fills, it flushes as an immutable sorted file — an **SSTable** — in one sequential write. Background **compaction** merge-sorts SSTables down through levels (each level roughly 10× the previous), dropping overwritten and deleted entries along the way.

    ```
    write → WAL (sequential append, durability)
          → memtable (in-memory, sorted)
          → [full] flush → SSTable at L0 (immutable, sequential write)
          → background compaction: L0 → L1 → L2 …  (merge, dedupe, drop deletes)
    ```

    The result: all foreground write I/O is sequential appends — memory-speed ingest — where a B-tree pays its reorganization cost inline on every write. This is why write-heavy workloads favor LSM engines (the Cassandra/RocksDB lineage), and why a Dynamo-style KV node runs one locally.

5. **The price is read and rewrite work — the three amplifications.** A point lookup may consult the memtable, every L0 file (their key ranges overlap, being independent flushes), and one file per lower level — **read amplification**. Compaction rewrites each key repeatedly as it migrates down levels — **write amplification**, routinely underestimated. Superseded versions occupy disk until reclaimed — **space amplification**. The three trade against each other, and tuning an LSM engine means choosing a point on the triangle:
    - **Leveled compaction** — non-overlapping ranges per level; minimizes read and space amplification at high write-amplification cost.
    - **Size-tiered compaction** — merge similar-sized SSTables when enough accumulate; lower write amplification, higher read and space amplification. Historically the write-heavy default.

6. **Read-amplification mitigations are standard equipment.** Per-SSTable Bloom filters (no false negatives, rare false positives) skip files that definitely lack the key; sparse in-memory fence pointers jump straight to the relevant block of a file; and compaction itself consolidates files so future reads touch fewer of them. An LSM deployment missing these is paying full read amplification for no reason.

7. **Immutability, buffering, ordering — the triad that explains most engine design.** *Buffering* governs when writes reach disk: accumulate and reorder many small random writes into few large sequential ones (the idea behind both memtables and WAL layout). *Immutability* governs whether existing bytes change: append-only segments make crash recovery trivial (a segment fully exists or doesn't) and reader/writer concurrency radically simpler — readers cannot race a mutation that never happens — at the cost of background garbage collection (compaction, vacuum). *Ordering* governs how data is arranged: sorted runs merge linearly and turn range access into sequential I/O. Key reframing: immutability doesn't remove the cost of change — it defers and batches it into background work.

8. **Batching generalizes buffering up the stack.** The same amortization that motivates memtables applies at every level: grouping many small operations into one large one spreads connection setup, transaction bookkeeping, fsync, and network round-trips across the whole batch — bulk row inserts instead of per-row statements, consumers polling messages in batches for throughput, settlement jobs processing payments in grouped runs. The costs are symmetrical: the tail item of a batch waits longest, a partially failed batch needs deliberate retry semantics (which items retry, which are poisoned), and batch size becomes an explicit tuning knob between throughput and latency.

9. **Indexes are the same trade in miniature.** Every secondary index buys read speed with extra storage plus write amplification — each insert/update/delete must maintain it. Over-indexing a write-heavy table degrades ingest the same way aggressive compaction does; index selection is really a choice about which query shapes to privilege. A clustered index (one per table, usually the primary key) dictates physical sort order and makes range scans on that key cheap; every non-clustered index pays an extra indirection — index lookup, then a second fetch from the data file — unless it is covering. Single-node transaction and locking discipline on top of these engines is covered in `python-dao-and-database`.

10. **Row vs column layout is the other physical fork.** Row stores keep all fields of one record adjacent — right for OLTP, where fetching or inserting a whole record touches one location, and wrong for analytics, where aggregating one column forces reading every full row. Column stores keep each column's values contiguous across all rows — right for OLAP scans over few columns of many rows, and they compress far better because same-column values are homogeneous; the mirror-image weakness is that reconstructing one full row touches many column files. Heuristic: "everything about one entity" → rows; "one attribute across millions of entities" → columns. Needing both at once is why OLTP/OLAP separation and ETL pipelines exist — don't ask one layout to serve both masters.

11. **Disk-based vs in-memory placement is a working-set question.** Disk engines keep the authoritative copy on durable storage and cache hot pages in a buffer pool; the entire discipline of indexes, prefetching, and sequential-write design exists to bridge the latency gap between RAM (nanoseconds) and storage (tens of microseconds for SSD random reads, milliseconds for spinning disk). In-memory engines remove disk from the hot path and reach microsecond latencies, but must re-engineer durability with snapshots and/or an append-only operation log replayed at restart — both built on sequential writes because those are the cheap kind. In practice most deployments are hybrids: a disk engine whose buffer pool covers the working set serves hot data at RAM speed anyway, so *working-set size relative to available RAM* is the first-order tuning question before any engine swap.

12. **B-tree variants exist for specific pain points — recognize them in engine documentation.** None replaces the classical B+tree as the general-purpose default; each answers exactly one weakness of in-place updates:
    - **Copy-on-write B-trees** — never mutate a page: writing a key produces a fresh copy of the whole root-to-leaf path, swapped in with one atomic root update. Crash safety comes nearly free (the old root always points at an intact tree) and readers are lock-free with snapshot semantics; the price is heavy write amplification.
    - **Bw-trees** — latch-free B-trees for many-core contention: updates are small delta records prepended with compare-and-swap through a logical-page mapping table, consolidated in the background. Costs: notorious implementation difficulty and delta-chain traversal on reads.
    - **Lazy / buffered B-trees** — park inserts in per-node buffers and push them to children in batches; defer rebalancing after deletes, betting a nearby insert makes the merge moot. Reads get more complex because they must consult buffered-but-unapplied operations on the way down.
    - **FD-trees** — flash-oriented hybrids: a small write buffer feeding a stack of exponentially larger immutable sorted runs — the same random-writes-into-sequential-ones trade that LSM trees generalize.

13. **Beware log-on-log stacking.** An LSM engine compacts at the logical level; a copy-on-write or log-structured filesystem underneath relocates those "sequential" writes again; the SSD's flash translation layer does its own log-structured remapping and garbage collection for wear-leveling below that. Each layer's cleanup looks efficient in isolation; together their independent GC passes duplicate and interfere, multiplying hidden write amplification. The remedy is mindful stacking: collapse layers where possible, or at minimum count how many log-structured layers the deployment stacks before trusting any write-amplification estimate.

14. **Match the family to the measured read/write mix.**

    | Profile | Engine family | Why |
    |---------|---------------|-----|
    | Read-heavy / mixed OLTP | B+tree | Predictable 1–2 page reads, cheap ranges, in-place updates |
    | Write-heavy ingest (events, telemetry, KV) | LSM | Sequential-only foreground I/O, memory-speed ingest |
    | Write-dominated, rarely read (logs) | LSM, relaxed/unordered variants | Even cheaper ingest, reads pay for it |

## Anti-patterns

1. **Mod-N placement with dynamic membership** — any node change remaps ~(N−1)/N of keys; for a cache tier that is a self-inflicted cluster wipe followed by a database stampede. Use consistent hashing with vnodes.
2. **A ring without virtual nodes** — uneven arcs, and a failed node doubles exactly one neighbor's load. If a design says "consistent hashing", ask "how many vnodes per node?"
3. **Sharding before exhausting cache, replicas, and vertical scale** — permanent complexity (no cross-shard joins or transactions, hard rebalancing, painful operations) taken on to solve a problem a cheaper rung of the ladder would have solved.
4. **Range-sharding on a monotonic key** — timestamps or auto-increment IDs aim every insert at the tail shard: a hot partition by construction.
5. **One global consistency mode** — forcing the like-counter through the funds-transfer quorum, or worse, the reverse. Tune N/W/R per workload and verify W+R>N wherever read-your-writes is actually required.
6. **Ignoring replication lag** — reading a replica immediately after writing the primary and shipping the "my edit disappeared" bug. Route lag-sensitive reads to the primary or a caught-up replica.
7. **Wall-clock timestamps for conflict ordering** — clocks drift; last-write-wins on wall time silently drops concurrent updates. Use logical/vector clocks and surface true conflicts (see `.claude/rules/resilience-engineering.md` on distributed time).
8. **Write-behind caching for data you can't lose** — a crash between acknowledgment and flush permanently loses those writes. Counters yes; money never.
9. **Treating the cache as a store of record** — if losing a cache node loses data, you've built an accidental KV store with none of the durability machinery (WAL, replication, hinted handoff, anti-entropy).
10. **Uniform TTLs on correlated hot keys** — synchronized expiry stampedes the origin in lockstep with the TTL. Jitter TTLs; add coalescing or stale-while-revalidate for hot entries.
11. **A single central health-checker** — a bottleneck that is itself a single point of failure, and one missed ping declaring death causes flapping. Gossip plus suspect-then-confirm (or phi-accrual) instead.
12. **Membership decisions without a majority quorum** — both sides of a partition electing leaders or claiming shards is split-brain; authoritative decisions need a majority so at most one side proceeds.
13. **Choosing a storage engine by fashion** — an LSM engine under a read-heavy OLTP app, or a B-tree under a raw event firehose, fights the engine's amplification profile all day. Match the family to the measured read/write mix.
14. **Indexing every column "just in case"** — each index is write amplification; on write-heavy tables the ingest cost arrives long before the read benefit does.
15. **Two-phase commit as the default cross-shard mechanism** — blocking locks, a coordinator that is both bottleneck and single point of failure, and messy recovery. Keep data that transacts together on one shard; reach for sagas and compensating transactions before 2PC.
16. **One layout serving OLTP and OLAP** — analytics scans crushing the row-store primary (or single-record traffic grinding a column store). Separate the workloads; that separation is what materialized views and ETL pipelines are for.

## References

Digests (own-words summaries of the source threads, in `references/`):

- [htn-design-consistent-hashing.md](references/htn-design-consistent-hashing.md) — mod-N failure math, the ring, vnodes (100–200/node), capacity weighting, production sightings
- [htn-design-a-distributed-key-value-store.md](references/htn-design-a-distributed-key-value-store.md) — Dynamo-style anatomy: RF=3 write-time replication, N/W/R worked examples, vector clocks, gossip cadence, LSM + WAL per node, coordination service
- [htn-design-a-distributed-cache.md](references/htn-design-a-distributed-cache.md) — speed-layer framing, cache-aside/write-through/write-behind heuristic, LRU/LFU + TTL, three invalidation strategies, cold start, plane separation
- [htn-tricky-hld-patterns-for-interviews.md](references/htn-tricky-hld-patterns-for-interviews.md) — write-behind trade-offs, thundering-herd defenses, read-replica architecture and lag, materialized views, bulk processing, pattern→bottleneck triage map
- [htn-databases-in-depth-part-1.md](references/htn-databases-in-depth-part-1.md) — engine layering, the page abstraction, why BSTs fail on disk, B+tree design, the buffering/immutability/ordering triad, index cost model
- [htn-databases-in-depth-part-3.md](references/htn-databases-in-depth-part-3.md) — LSM anatomy (memtable/WAL/SSTable/levels), the three amplifications, leveled vs size-tiered compaction, B-tree variants (COW, Bw-tree)

Attribution: the htn-* digests are synthesized from public X threads by Harshit Khosla (@Harry_The_Nerd) — own-words summaries, no verbatim text.

Related skills and rules:

- `system-design-patterns` — system-scale building blocks (gateways, queues, fan-out, rate limiting) that sit above this data tier
- `redis-caching-patterns` — concrete single-cluster cache implementation: namespacing, SCAN invalidation, stampede locks, in-memory fallback
- `python-dao-and-database` — single-node transactions, locking, and DAO discipline on top of the storage engines described here
- `.claude/rules/resilience-engineering.md` (always loaded) — owns CAP/PACELC partition behavior, distributed-time/clock correctness, retries, circuit breakers, backpressure, and chaos verification
