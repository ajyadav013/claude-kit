# Digest: Databases in Depth — Part 1 (Foundations, Storage, and B-Trees)

- **Source:** https://x.com/Harry_The_Nerd/status/2073772366094602241
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Backend Engineering
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Layered DBMS architecture

A database engine decomposes into three broad layers: a query processor (SQL parsing into an AST,
cost-based plan selection, plan execution), a storage engine, and a client/wire-protocol layer
handling connections and auth. The storage engine itself subdivides into access methods (B-trees,
LSM trees, hash indexes), a buffer manager for cached pages, a transaction manager (locking,
isolation, MVCC), and a recovery manager (WAL, checkpoints, crash restart). The author's framing:
the differentiation between engines like Postgres, MySQL, Cassandra, and RocksDB lives almost
entirely in the storage engine, because that is the layer where hardware realities (seek cost,
page size, cache locality) collide with software. A DBMS is essentially a mapper between the
application's logical model (tables/rows) and a physical byte layout tuned for the medium.

**When to use this mental model:** any time you are reasoning about why one engine behaves
differently from another — compare storage engines, not SQL dialects.

### Disk-based vs in-memory database placement

The first big architectural fork is where the authoritative copy of data lives. Disk-based engines
(Postgres, MySQL, Oracle) keep data on durable, cheap storage and cache hot pages in RAM; the whole
discipline of buffer pools, indexes, prefetching, and sequential-write design exists to compensate
for the latency gap (memory access in nanoseconds; SSD random reads around tens of microseconds;
spinning-disk random reads in the millisecond range). In-memory engines (Redis, Memcached,
SAP HANA, VoltDB) remove disk from the hot path and reach microsecond latencies, but must
re-engineer durability via periodic snapshots (e.g. Redis RDB) and/or an append-only operation log
replayed at restart (e.g. Redis AOF) — both chosen because sequential disk writes are far cheaper
than random ones. Trade-off axes: RAM cost and dataset-size ceiling versus latency; durability
comes for free on disk but requires extra machinery in memory. In practice most deployments are
hybrids — a disk engine with a big enough buffer pool serves hot data from RAM — so knowing your
working-set size relative to available RAM is a first-order tuning concern.

### Row-oriented vs column-oriented physical layout

Row stores keep all fields of one record adjacent on disk, which suits OLTP: fetching or inserting
a whole record touches one location. The cost appears in analytics — aggregating one column forces
reading every full row, wasting I/O on fields the query ignores. Column stores keep each column's
values contiguous across all rows, which suits OLAP scans and aggregations over few columns of many
rows, and compresses far better because same-column values are homogeneous (run-length encoding a
repetitive column beats compressing a mixed-type row). Examples cited: Redshift, ClickHouse,
BigQuery, Cassandra's SSTable format, and Parquet. The mirror-image weakness: reconstructing one
full row from a column store requires touching many column files, so it is a bad fit for
single-record OLTP traffic. Heuristic: "everything about one entity" → row layout; "one attribute
across millions of entities" → column layout. Needing both is why OLTP/OLAP separation, ETL
pipelines, and HTAP research exist.

### Data files vs index files; clustered/non-clustered and primary/secondary indexes

The data file is the authoritative record store; an index file is an auxiliary map from a search
key to the record's location, holding only the key plus a pointer/offset, never the whole row.
A clustered index dictates the physical sort order of the table (one per table, usually the
primary key), making range scans on that key cheap because target rows sit adjacent on disk —
InnoDB stores full rows in the primary-key B-tree's leaves for exactly this reason. Non-clustered
indexes are separate structures (many allowed) that pay an extra indirection: index lookup, then a
second fetch from the data file — unless the index is covering, i.e. contains every column the
query needs. Storage-engine literature frames the same idea as primary (built on the data file's
sort key) versus secondary (any other field, always indirected) indexes. Core trade-off: each index
buys read speed with extra storage plus write amplification, since every insert/update/delete must
maintain it — over-indexing degrades write throughput, and index selection is really a choice about
which query shapes to privilege.

### Buffering: batching writes and caching reads

Nearly every engine interposes RAM between the application and disk. Read side: a buffer pool holds
hot pages so repeated reads skip the disk, with eviction governed by LRU/LFU variants or hybrids
such as Postgres's clock-sweep. Write side: buffering lets the engine accumulate and reorder many
small random writes into fewer large sequential ones — one of the biggest single levers on write
performance, and the underlying idea behind LSM memtables and append-only WAL layout. The risk is
losing buffered-but-unflushed data on a crash; write-ahead logging is the standard answer — durably
append the intent first, apply the buffered change to data files later, and replay the log after a
crash to recover anything not yet flushed.

### Immutability: never update in place

Modern storage engines increasingly write new versions instead of mutating existing bytes. Payoffs:
(1) reader/writer concurrency simplifies radically — readers cannot race a mutation that never
happens, which is the basis of MVCC snapshots in Postgres and InnoDB; (2) crash recovery gets
easier because an append-only segment either fully exists or does not, with no half-overwritten
state; (3) writes become sequential by default, matching what disks do well. The cost is garbage:
superseded versions accumulate and must be reclaimed by background work — compaction in LSM
systems, vacuum in Postgres. The author's key reframing: immutability does not remove the cost of
change, it defers and batches it into background processes instead of paying inline per write.

### Ordering: sorted data enables ranges and merges

Keeping data sorted — physically (clustering by primary key), within index nodes, or per segment
(sorted SSTables) — is what makes range queries, ordered scans, and efficient merging possible.
Sorted runs can be merged linearly (the mechanism behind LSM compaction, analogous to merge sort's
merge step), and sorted adjacency converts range access into sequential I/O. The author's compact
triad: buffering governs *when* writes reach disk, immutability governs *whether* existing bytes
change, ordering governs *how* data is arranged for retrieval and merging — three lenses that
explain most storage-engine design choices.

### Why binary search trees fail on disk

A BST gives O(log n) operations via halving the search space, but assumes uniform random-access
cost, which holds in RAM and collapses on disk. A million-entry binary tree is about 20 levels deep
(log2 of one million), and if each tiny node lands at an arbitrary disk location, one lookup can
cost up to 20 random seeks — potentially milliseconds each. The right cost metric for a disk
structure is pages read, not comparisons made, which motivates redesigning the tree around the
storage medium.

### The page abstraction as the design driver

Storage hardware transfers fixed-size blocks (pages of 4KB, 8KB, or 16KB), and reading one byte of
a page costs about the same as reading the whole page. Therefore a disk structure should make each
node fill a page: with roughly 100 keys and 101 child pointers per page, a million-key tree needs
about 3 levels instead of a BST's ~20. The general trick is trading depth for width — many keys per
node, huge branching factor, few levels — which directly minimizes the count of expensive page
reads per operation.

### B-trees / B+trees: the default index structure

The production variant is the B+tree: page-sized nodes holding many sorted keys; all leaves at
identical depth (uniform, predictable lookup cost); nodes bounded by min/max occupancy, with
overflow handled by splitting and promoting a separator key upward, and underflow by borrowing from
or merging with siblings. B+tree-specific properties: internal nodes carry only routing keys (no
row data), maximizing fanout and flattening the tree; leaves hold the data (or row pointers) and
are chained in a sorted linked list, so a range query finds its start once and then walks leaves
sequentially instead of re-descending the tree.

**Why this structure won** (per the author): huge fanout keeps billion-row datasets at 3–4 levels,
and since the small upper levels stay cached, real lookups often cost only 1–2 physical reads;
splits/merges keep the tree balanced by construction with no degenerate cases; linked leaves make
the very common range/ORDER BY patterns cheap; in-place updates keep read latency predictable;
and ~5 decades of maturity mean concurrency (e.g. latch crabbing), recovery integration, and bulk
loading are well-solved. Used across Postgres, MySQL/InnoDB, Oracle, SQL Server, and SQLite.

### B-tree vs LSM-tree trade-off axis

The closing contrast: B-trees buy read latency and predictable in-place updates at some write cost
(updates can cascade into splits/merges); LSM trees invert this, maximizing write throughput via
immutable append-only runs merged by background compaction, at the price of read amplification.
The author positions this divide as the central fault line in modern storage-engine design and the
subject of the series' next part. Practical guidance embedded here: B-trees are the sound
general-purpose default for read-heavy or mixed OLTP workloads.

### Meta-principle: physical constraints shape logical design

The article's unifying thesis: every design above — layering, memory/disk placement, row/column
layout, indexing, buffering, immutability, ordering, B-trees — is a downstream consequence of what
disks and RAM are respectively good and bad at. Useful as a first question when evaluating any
storage system: which hardware constraint is this design compensating for?

## Not absorbed

- Series greeting and framing ("continuing my backend-engineering series", three-part plan
  announcement) — publication logistics, not engineering content.
- The 3 AM incident / "we curse databases" color and the "intuition instead of folklore"
  motivational framing — rhetorical setup only.
- "Stay tuned", like/comment/repost/share calls to action, and the sign-off — audience-growth
  promotion.
- Engagement metrics captured with the post (10k views, reply/repost/like counts) — platform
  metadata, not article content.

## Fidelity check

- **Post count in capture:** 1 (a single long-form article post; `postCount: 1` in the capture
  JSON, no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline as authored:**
  1. Intro / series framing
  2. DBMS Architecture
  3. Memory vs Disk-Based DBMS (Disk-based DBMS; Memory-based (in-memory) DBMS)
  4. Column-Oriented vs Row-Oriented DBMS (Row-oriented storage; Column-oriented storage)
  5. Data Files and Index Files (Clustered vs non-clustered indexes; Primary vs secondary index files)
  6. Buffering, Immutability, and Ordering (Buffering; Immutability; Ordering)
  7. Binary Search Trees: The Starting Point
  8. Disk-Based Structures and the Page Abstraction
  9. B-Trees: The Ubiquitous Index Structure (including the "why B-trees won" discussion)
  10. Closing theme (physical constraints shape logical design) and calls to action
- **Pattern-to-section citations:**
  - Layered DBMS architecture → section 2 (DBMS Architecture)
  - Disk-based vs in-memory placement → section 3 (Memory vs Disk-Based DBMS)
  - Row vs column layout → section 4 (Column-Oriented vs Row-Oriented DBMS)
  - Data/index files, clustered/non-clustered, primary/secondary → section 5 (Data Files and Index Files)
  - Buffering → section 6, "Buffering" subsection
  - Immutability → section 6, "Immutability" subsection
  - Ordering → section 6, "Ordering" subsection
  - Why BSTs fail on disk → section 7 (Binary Search Trees: The Starting Point)
  - Page abstraction → section 8 (Disk-Based Structures and the Page Abstraction)
  - B+tree structure and "why B-trees won" → section 9 (B-Trees: The Ubiquitous Index Structure)
  - B-tree vs LSM trade-off → section 9, closing paragraphs
  - Physical-constraints meta-principle → section 10 (closing theme)
- **Capture oddities:** the row-store illustration in the source is internally inconsistent — the
  second example row is named one thing in the record listing and a different name in the on-disk
  byte sequence; noted here as a source typo, not reproduced. The capture is one flattened text
  blob including trailing engagement counts and the 5 Jul 2026 timestamp.
