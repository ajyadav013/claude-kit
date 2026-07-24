# distributed-systems-patterns

Distributed data-tier design patterns — how keys find nodes, how data survives failures, how consistency is tuned per workload, and what storage engine runs underneath.

## What this covers

- **Consistent hashing**: the mod-N reshuffle failure, the ring, virtual nodes (100–200/node), capacity weighting, bounded key movement
- **Partitioning & sharding**: hash vs range vs directory schemes, hot-partition defenses, and the scaling ladder (cache → replicas → shard last)
- **Replication & quorum**: leader-follower vs leaderless, N/W/R tuning per workload, W+R>N read-your-writes, lag-aware read routing
- **Distributed KV-store anatomy**: coordinator + preference list, hinted handoff, read repair, Merkle-tree anti-entropy, vector clocks vs LWW
- **Distributed cache design**: speed-layer framing, cache-aside/write-through/write-behind, eviction, invalidation, hot keys, thundering herd
- **Failure detection & gossip**: suspect-then-confirm heartbeats, phi-accrual in plain terms, gossip dissemination, split-brain awareness
- **Storage engines**: page abstraction, B+tree vs LSM (memtable/WAL/SSTable/compaction), the three amplifications, indexes as a read/write trade

## Origin

Synthesized from own-words digests of public X threads by Harshit Khosla (@Harry_The_Nerd) — no verbatim text. The digests live in `references/` with per-section fidelity checks against the source articles.

## Structure

- `SKILL.md` — the full skill: core sections, anti-patterns, and cross-links
- `references/htn-*.md` — six source digests (consistent hashing, KV store, distributed cache, tricky HLD patterns, databases in depth parts 1 and 3)

## Usage

Read this skill when designing or reviewing a sharded, replicated, or cached data tier. Cross-links: `system-design-patterns` for system-scale composition, `redis-caching-patterns` for concrete cache implementation, `python-dao-and-database` for single-node transactions, and `.claude/rules/resilience-engineering.md` (always loaded) for CAP/PACELC, clocks, retries, circuit breakers, and backpressure.
