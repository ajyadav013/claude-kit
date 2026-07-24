# Design Autocomplete For Search Engines

- **Source:** https://x.com/Harry_The_Nerd/status/2045906641967833171
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Latency budget as the shaping constraint

The whole design is derived from one non-functional requirement: a suggestion request fires on every keystroke, so the round trip has to land inside roughly 100ms, with 50ms as the real target. When to use: any per-keystroke or per-interaction feature where the request rate equals the typing rate, not the page-view rate. Trade-off: hitting that budget forces everything read-side into memory and pushes all expensive work (frequency counting, ranking) off the request path entirely.

### Trie (prefix tree) as the lookup structure

Store the suggestion corpus as a character-per-node tree so that walking the typed prefix lands you at a node whose subtree contains exactly the valid completions. Lookup cost is O(prefix length) and does not grow with corpus size. When to use: prefix-match workloads (autocomplete, typeahead, command palettes). Trade-off: the structure is memory-hungry and awkward to mutate under concurrent load, which drives the batch-rebuild and sharding decisions below.

### Precomputed top-N per node (frequency + priority queue)

A prefix like a common three-letter stem can have thousands of completions but the UI shows only 5-10, so each trie node carries a cached, frequency-ordered list of the top N completions reachable beneath it, maintained via a max-oriented priority queue on search counts. Query time then does zero ranking work — it just reads the node's cached list. When to use: whenever the ranked result for a query class is stable enough to precompute. Trade-off: you pay storage at every node and the cached ranks are only as fresh as the last rebuild.

### Batch rebuild instead of in-place writes (eventual consistency)

At Google-like scale — about 8.5 billion searches/day, roughly 100k/s — letting every search mutate the live in-memory trie would mean 100k concurrent writers contending with millions of readers on the hottest structure in the system. Instead, searches are appended asynchronously to a Kafka log, a Spark batch job runs every few hours to recount frequencies from the accumulated logs, rebuilds the trie offline, persists it, and the serving fleet swaps in the fresh snapshot. Users always read a snapshot that is hours stale, which is imperceptible for this workload. When to use: read-hot structures whose freshness requirement is soft. Trade-off: newly trending queries take up to one rebuild cycle to surface; you trade recency for read-path stability.

### Traffic-weighted trie sharding

The full trie exceeds one machine, so it is partitioned by prefix range across servers — but by traffic share, not by an even alphabetical split, because letter popularity is wildly skewed (an "s"-heavy prefix space can justify a dedicated shard while a dozen quiet letters share one). When to use: any keyspace partitioning where load per key range is non-uniform. Trade-off: the mapping is irregular and must be maintained and rebalanced as traffic shifts, which introduces the next component.

### Coordination service for shard routing

A Zookeeper-style coordination service owns the prefix-range-to-server map; each incoming request consults it (microsecond-scale) and is routed to the shard that holds that prefix. When to use: dynamic shard maps that must stay consistent across a fleet. Trade-off: an extra hop and a coordination dependency on the read path, bought back by the ability to resize/rebalance shards without client changes.

### Two-store split: write-optimized log DB vs. durable + in-memory serving pair

Storage is divided by access pattern. Raw search events (id, user, query, timestamp, location) go to Cassandra, chosen for horizontal scale and very high write throughput — billions of appends per day is its natural regime — and this store feeds the batch job. The rebuilt trie itself is serialized to S3 as the durable source of truth, and each shard server loads its slice into Redis for in-memory reads. When to use: separate the append-heavy raw-event path from the latency-critical serving path rather than forcing one database to do both. Trade-off: more moving parts, but each store runs in its sweet spot; S3 gives durability without slowing reads, Redis gives speed without owning persistence.

### Availability via replication at every layer

Each trie shard runs replicas so a failed server hands over without user-visible interruption; Kafka retains the search log so a delayed batch job loses nothing; S3 holds the canonical trie so a Redis wipe is recoverable by reloading on restart. When to use: standard layered-redundancy checklist for any read-serving pipeline with an offline build step. Trade-off: replica cost and snapshot-reload time versus a single point of failure at each layer.

### End-to-end read/write flow

The composed architecture: keystroke → API gateway → coordination lookup → correct shard → Redis-resident trie returns the precomputed top suggestions inside the ~50ms budget; in parallel the search event is logged to Kafka, and the periodic Spark job reads Cassandra logs, recounts, rebuilds, writes to S3, and refreshes Redis. The read path and the update path never touch the same structure at the same time — that separation is the article's central idea.

## Not absorbed

- Series branding ("High-Level Design Question-based Series #4") and the "let's go, legends" / "that's all folks" hype framing — interview-prep packaging, not engineering content.
- The opening hook about typing into Google and the closing sign-off — motivational framing only.
- The illustrative per-completion search counts in the ranking example (9M / 7M / 4M / 1M / 800k) — made-up demo values, absorbed only as "frequency-ordered top-N", not as real capacity data.
- Post-footer engagement metrics (views/replies/likes) and timestamp — capture artifacts of the render, not article content.

## Fidelity check

- **Post count in capture:** 1 (a single long-form article post; no thread breaks present).
- **Article outline as the author structured it:**
  1. Intro / hook (autocomplete as a latency-sensitive, data-heavy design problem)
  2. Functional requirements
  3. Non-functional requirements (latency-first framing)
  4. The core data structure is Trie
  5. Ranking suggestions — frequency + priority queue
  6. The update problem — why real-time writes don't work (batch pipeline: Kafka → Spark → rebuild)
  7. Splitting the Trie — sharding (traffic-based ranges + Zookeeper)
  8. The database layer — two stores (Cassandra log DB; S3 + Redis trie store)
  9. The full architecture (end-to-end flow diagram)
  10. Non-functional requirements revisited (latency, scalability, availability)
  11. Sign-off
- **Pattern-to-section citations:**
  - Latency budget as the shaping constraint → sections 3 and 10 ("Non-functional requirements", both passes)
  - Trie (prefix tree) as the lookup structure → section 4 ("The core data structure is Trie")
  - Precomputed top-N per node → section 5 ("Ranking suggestions == frequency + priority queue")
  - Batch rebuild instead of in-place writes → section 6 ("The update problem")
  - Traffic-weighted trie sharding → section 7 ("Splitting the Trie - sharding")
  - Coordination service for shard routing → section 7 ("Splitting the Trie - sharding")
  - Two-store split → section 8 ("The database layer - two stores")
  - Availability via replication at every layer → section 10 ("Non-functional requirements", availability subsection)
  - End-to-end read/write flow → section 9 ("The full architecture")
