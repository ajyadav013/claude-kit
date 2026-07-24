# Digest: Databases in Depth — Part 3 (B-Tree Variants and Log-Structured Storage)

- **Source:** https://x.com/Harry_The_Nerd/status/2076649413435687097
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Backend Engineering
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

Part 3 of a three-part series on storage-engine internals. Parts 1–2 derived the classical
B-tree from disk physics (pages, slotted layouts, split/merge rebalancing). This installment
surveys (a) B-tree variants that each fix a specific weakness of the in-place design, and
(b) the log-structured family (LSM trees and relatives), framing both as different answers to
the same physical cost model.

## Patterns

### Copy-on-write (COW) B-trees
Never mutate a page in place: writing a key produces a fresh copy of the leaf, plus fresh
copies of every ancestor up to the root (each parent must point at the new child), and the
new root is swapped in with one atomic pointer update. Crash safety comes essentially free —
mid-write failure leaves the old root pointing at a fully intact prior tree, so no undo
logging of tree structure is needed. Readers are lock-free: they pin whatever root was
current when they started, which also gives snapshot semantics analogous to MVCC but at
whole-tree granularity. Trade-off: heavy write amplification, since one key change rewrites
the entire root-to-leaf path. LMDB is the canonical production example. Use when read-heavy
workloads and crash-consistency simplicity matter more than write cost.

### Indirection layers (logical page IDs + mapping table)
Instead of parents storing raw disk offsets, they store logical page IDs resolved through a
separate translation table. Relocating a page (compaction, defrag, SSD wear-leveling) then
means updating one table entry rather than rewriting every referencing ancestor, and it
enables partial copy-on-write where only the mapping changes. This is the conceptual
ancestor of the Bw-tree. Cost: one extra level of lookup on every access, plus the table
itself to maintain.

### Lazy B-trees / buffered structural maintenance
Defer structural work instead of doing it synchronously per operation. Two forms described:
(1) buffer-tree style — internal nodes hold per-node write buffers; inserts/deletes park in
a buffer and are pushed down to children in batches only when the buffer fills, amortizing
root-to-leaf traversal across many writes; (2) deferred rebalancing — after a delete, leave
a leaf temporarily underfull rather than merging immediately, betting a nearby insert will
soon make the merge moot, which avoids split/merge thrash under interleaved workloads.
Trade-off: reads get more complex because they must also consult buffered-but-unapplied
operations at interior levels on the way down.

### FD-trees (flash-oriented B-tree/LSM hybrid)
Built for SSD characteristics: random reads are fine, random writes are costly (block
erase-and-rewrite, flash wear). Design: a small in-memory write buffer feeding a stack of
immutable, sorted on-disk runs whose sizes grow exponentially by level; when the buffer
fills it merges down as sequential batch writes. Small in-memory indexes per level (fence
pointers, originally fractional cascading) route lookups without scanning every level. The
core insight — trade read complexity for turning random writes into sequential ones — is
the same one LSM trees generalize; the article positions FD-trees as historically important
for legitimizing that trade-off for flash hardware.

### Bw-trees (latch-free B-trees via CAS + delta chains)
Targets latch contention on hot pages under many-core concurrency. Combines the indirection
mapping table with lock-free updates: a modification is a small delta record atomically
prepended (compare-and-swap) to a per-page delta chain keyed by logical page ID; readers
replay base page + deltas to reconstruct current state. When a chain grows long, it is
consolidated into a new base page and swapped in — again via CAS, never a lock. Because
pages are never modified in place, updates flush as append-only sequential I/O, tying the
design to log-structured storage. Origin: Microsoft Research (Hekaton, later SQL
Server/Azure storage components). Costs: notorious lock-free implementation difficulty and
read overhead from chain traversal.

### Cache-oblivious B-trees (van Emde Boas layout)
Optimizes for the full CPU cache hierarchy (L1/L2/L3/RAM), not just disk-vs-memory. Rather
than tuning node sizes to a specific cache ("cache-aware"), a cache-oblivious layout is
recursively self-similar: divide the tree into an upper portion and lower sub-trees, then
apply the same subdivision inside each piece. Whatever the cache size on a given machine, some level of
the recursion matches it, so cache-line-sized chunks of the tree land contiguously — near-
optimal at every hierarchy level with zero tuning parameters. Mostly academic/specialized in
practice, since empirically tuned cache-aware sizing gets comparable real-world results, but
the "design layout for the whole memory hierarchy" idea has broader influence.

### LSM tree architecture
The other major storage paradigm: append-only log plus background reorganization, instead
of an updatable page tree. Components: a **memtable** (in-memory sorted structure, commonly
a skip list) absorbing all writes with zero disk I/O on the hot path; a **write-ahead log**
(sequential appends) so the volatile memtable can be rebuilt after a crash; **SSTables** —
when the memtable hits a size threshold it flushes as an immutable sorted file via one
sequential write; and **levels** (L0, L1, L2, …), each level roughly 10x the size of the
previous one, with background compaction merge-sorting SSTables downward and dropping
overwritten/obsolete entries. Payoff: all foreground writes become sequential appends,
versus a B-tree paying its organization cost inline on every write.

### Read amplification and its mitigations
A point lookup may need to consult the memtable, every L0 file (L0 files can have
overlapping key ranges since they are independent memtable flushes), and one file per lower
level — read amplification is that actual-reads-to-necessary-reads ratio. Standard
mitigations: **Bloom filters** per SSTable (no false negatives, rare false positives) to
skip files that definitely lack the key; **fence pointers / sparse in-memory indexes** to
jump straight to the relevant block of a file; and **compaction itself**, which consolidates
files so future reads touch fewer of them.

### Write and space amplification; the three-way tension
LSM trees, despite being write-optimized, rewrite each key repeatedly as compaction migrates
it L0→L1→L2… — write amplification is physical-bytes-written over logical-bytes-written and
is frequently underestimated. Space amplification is disk consumed beyond logical data size
(not-yet-reclaimed overwrites/deletes, redundancy across levels). The three amplifications
trade against each other: aggressive compaction lowers read and space amplification but
raises write amplification; relaxed compaction does the opposite. Tuning an LSM system
largely means choosing a point on this triangle for the workload.

### Compaction strategies: leveled vs size-tiered
**Leveled** (RocksDB/LevelDB default): each level below L0 keeps non-overlapping sorted key
ranges, each level a fixed multiple larger; compaction merges level-N files into overlapping
level-N+1 files. Minimizes read amplification (at most one file per level) and space
amplification, at the price of high write amplification. **Size-tiered** (historically a
common Cassandra default for write-heavy loads): merge similar-sized SSTables once enough
accumulate, without strict non-overlap. Lower write amplification, higher read and space
amplification. Modern engines (RocksDB notably) support both plus hybrids that vary strategy
by level; choose based on the workload's read/write balance.

### Unordered LSM storage
Relax the sorted-level invariant: group incoming writes by arrival time or hash, defer (or
skip) global sorting, and layer secondary indexes over unsorted segments for lookups. Trades
slower index-assisted point reads for even cheaper ingestion. Fits write-dominated,
rarely-read workloads — logging, telemetry, event ingestion — not typical OLTP.

### LSM concurrency via immutability
Because SSTables never change after being written, readers never coordinate with writers on
them — the entire latch problem the Bw-tree fights in the B-tree world simply does not
exist for immutable files. Remaining coordination is narrow: the mutable memtable (usually a
concurrent skip list or another low-lock design) and compaction handoff (retiring old
SSTables safely under in-flight reads, via reference counting or epoch-based reclamation so
a file is not deleted while still being read).

### The log-stacking ("log on log") problem
Layering log-structured systems compounds hidden write amplification: an LSM database does
compaction at the logical level, a log-structured or copy-on-write filesystem below it
relocates those "sequential" writes again, and the SSD's flash translation layer underneath
does its own log-structured remapping and garbage collection for wear-leveling. Each layer
optimizes in isolation and each looks efficient alone, but their independent GC/compaction
passes duplicate and interfere with one another.

### LLAMA and mindful stacking
LLAMA (latch-free, log-structured, access-method-aware storage layer, from the same
Microsoft Research effort as the Bw-tree) answers log stacking by making the storage layer
explicitly aware of the access method above it (the Bw-tree's delta chains and mapping
table), so flushing, compaction, and space reclamation exploit knowledge of how data is
actually used and invalidated. The generalized principle — "mindful stacking" — is to
either collapse layers (e.g., the database managing raw block devices/flash directly,
bypassing the filesystem) or make adjacent layers mutually aware, eliminating redundant
garbage-collection passes and avoiding writing one logical change to multiple journals.

### Series meta-principle: physical costs drive design
The closing synthesis: every structure across the three parts — classical B-tree, COW/Bw/
cache-oblivious variants, the whole LSM family — is a different resolution of the same
constraint set (disk vs memory latency, page I/O, sequential vs random access, cache
hierarchies). There is no universally best structure, only positions on read-optimized vs
write-optimized, simplicity vs throughput, latch-based vs lock-free trade-off axes;
transferable skill is reasoning about those axes, not memorizing which engine uses what.

## Not absorbed

- Opening greeting and Parts 1–2 recap paragraphs — series continuity framing, no new
  engineering content beyond what the pattern sections restate.
- "That's all, folks..Cheers!!" sign-off — closing pleasantry.
- Trailing engagement metadata (timestamp, view/reply/like counts) — platform chrome, not
  article content.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; `postCount: 1` in the JSON,
  no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline (author's structure):**
  1. Intro — recap of Parts 1–2, scope of Part 3
  2. B-Tree Variants (section intro: pain points of in-place updates)
     1. Copy-on-write B-trees
     2. Abstracting node updates (indirection layers)
     3. Lazy B-trees
     4. FD-Trees (Flash Disk Trees)
     5. Bw-Trees (latch-free B-trees)
     6. Cache-oblivious B-trees
  3. Log-Structured Storage (section intro: append-only philosophy)
     1. The core idea: LSM Trees (memtable / WAL / SSTables / levels)
     2. Read amplification
     3. Write amplification
     4. Space amplification
     5. Implementation details: compaction strategies
     6. Unordered LSM storage
     7. Concurrency in LSM trees
     8. Log stacking
     9. LLAMA and mindful stacking
  4. Closing — "That's it for Databases in Depth" synthesis on physical constraints and
     trade-offs
- **Pattern-to-section citations:**
  - Copy-on-write B-trees → §2.1 "Copy-on-write B-trees"
  - Indirection layers → §2.2 "Abstracting node updates (indirection layers)"
  - Lazy B-trees / buffered maintenance → §2.3 "Lazy B-trees"
  - FD-trees → §2.4 "FD-Trees (Flash Disk Trees)"
  - Bw-trees → §2.5 "Bw-Trees"
  - Cache-oblivious B-trees → §2.6 "Cache-oblivious B-trees"
  - LSM tree architecture → §3.1 "The core idea: LSM Trees"
  - Read amplification and mitigations → §3.2 "Read amplification"
  - Write/space amplification tension → §3.3 "Write amplification" + §3.4 "Space
    amplification"
  - Leveled vs size-tiered compaction → §3.5 "Implementation details: compaction strategies"
  - Unordered LSM storage → §3.6 "Unordered LSM storage"
  - LSM concurrency via immutability → §3.7 "Concurrency in LSM trees"
  - Log stacking → §3.8 "Log stacking"
  - LLAMA / mindful stacking → §3.9 "LLAMA and mindful stacking"
  - Physical-costs meta-principle → §4 closing synthesis
