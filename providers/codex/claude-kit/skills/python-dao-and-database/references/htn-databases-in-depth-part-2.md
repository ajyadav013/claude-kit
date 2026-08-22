# Digest: Databases in Depth — Part 2 (File Formats, B-Tree Implementation, Transaction Processing)

- **Source:** https://x.com/Harry_The_Nerd/status/2075942037732667812
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Backend Engineering
- **Fetched:** 2026-07-23/24 via logged-out browser render (article posted 11 Jul 2026)
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

Part 2 of the author's database-internals series. Part 1 covered the conceptual layer (DBMS
architecture, memory/disk trade-offs, row vs column storage, why B-trees win); this installment
descends to the implementation layer: how bytes are laid out on disk, how a B+tree is built on
top of a page format, and how a database stays correct under concurrency and crashes.

## Patterns

### Binary on-disk encoding principles

Database engines store data as binary, not text: it is denser, parseable by direct offset math,
and size-deterministic — a property page-based storage depends on. Recurring design decisions in
any binary format: (a) fixed-width fields readable at a known offset vs variable-width fields
carrying a length prefix (the standard choice over delimiters, since a prefix removes ambiguity
and lets a reader skip a value without scanning it); (b) a single enforced endianness so files
are portable across machines; (c) optional padding so multi-byte values sit on natural alignment
boundaries, trading a few bytes for faster CPU access; (d) per-page or per-record checksums
(CRC32 is typical) so corruption and torn writes are detected instead of silently served; (e)
a magic number plus a format-version field in the header so the engine can reject foreign or
incompatible files and evolve the format later.

### Fixed-size page anatomy

Disk-resident engines carve storage into fixed pages (4KB/8KB/16KB). Regardless of what a page
holds, the same anatomy recurs: a header (page ID, page type such as leaf/internal/overflow/free,
checksum, record count, free-space pointers, and often an LSN tying the page to the write-ahead
log for recovery); a slot/cell-pointer array of offsets growing from the front; the serialized
records packed from the back; and the shrinking free region between them. SQLite, Postgres, and
InnoDB all follow this shape with local variations.

### Slotted pages (indirection for variable-length records)

The problem: hold variable-length records in a fixed page while supporting cheap insert/delete.
Packing records back-to-back fails — deleting mid-page either leaves holes or forces shifting
everything, which also breaks any external pointer into the page. The slotted design inserts one
level of indirection: outside references (parent B-tree nodes, row IDs) name a stable slot
number; only the small slot array maps slots to byte offsets. Records can then be moved or
compacted inside the page without touching external references; deletion is nulling a slot and
reclaiming the bytes lazily; and logical key order can be maintained by sorting the tiny slot
array instead of physically reordering variable-length payloads. Fragmentation stays contained
because a compaction pass can defragment the content area independently of slot order.

### Cell layout

A cell is the serialized unit inside a page: a row in a data page, or key+child-pointer
(internal) / key+value-or-row-pointer (leaf) in an index page. Typical fields: a length header
(cells are variable-size), the key encoded per its type (fixed-width numerics, length-prefixed
strings), then either the inline payload (e.g., the whole row in a clustered-index leaf) or a
reference to it (row ID or overflow-page pointer), plus optional metadata such as a tombstone
flag for soft deletes or version info for MVCC engines.

### Overflow pages for oversized values

Large text/blob/JSON values that would dominate a page are split: engines cap the fraction of a
page one cell may occupy, store a prefix of the value inline with a pointer to a chain of
overflow pages holding the rest. Keeping in-page cell sizes bounded keeps fanout high and split
logic simple — one huge row cannot starve its neighbors.

### B-tree-specific page metadata

On top of the generic header, B-tree pages add: a node-type flag (internal vs leaf, which decides
how cells are interpreted); a key count checked against the min/max bounds that trigger
rebalancing; in B+trees, a right-sibling pointer on leaves forming the linked list that makes
range scans cheap; and optionally a parent pointer — some engines keep one to simplify
split/merge propagation, but many skip it (tracking the descent path at traversal time instead)
because maintaining parent pointers adds write cost.

### Binary search inside a node

Keys within a node are sorted, so locating the right child or record is a binary search over the
slot array — O(log k) comparisons for k keys per node (typically hundreds), not a linear scan.
The headline O(log n) B-tree cost counts disk page reads; each page visit internally does its own
binary search.

### Insertion with split propagation

Insert = root-to-leaf descent (binary search per level), place the key in sorted position in the
leaf. On overflow, the leaf splits into two roughly equal halves in a freshly allocated page, and
a separator key (middle key, or first key of the right half, depending on variant) is pushed into
the parent with a pointer to the new sibling. That push can overflow the parent, which splits in
turn — splits cascade upward, and if the root splits, a new root is created and tree height grows
by exactly one. Growing only at the root is why every leaf stays at equal depth: the tree is
height-balanced by construction rather than by repair.

### Deletion with borrow/merge and upward rebalancing

The mirror operation, and harder to get right. After removing a key, a leaf above the minimum
occupancy needs nothing more. On underflow there are two moves: borrow from an adjacent sibling
that has spare keys (a key rotates through the parent; cheaper and preferred), or merge with a
sibling that is itself at minimum, deleting the separator key from the parent. Removing that
separator can underflow the parent, so merges also propagate upward; if the root is left with a
single child, that child becomes the new root and height shrinks by one. This split/borrow/merge
machinery is the concrete meaning of "self-balancing" — invariants are enforced on every mutation,
so worst-case height (and disk reads per operation) stays bounded, unlike a plain BST that a bad
insert order can skew.

### Right-only append optimization for monotonic keys

Auto-increment IDs, timestamps, and sequence keys mean every insert targets the rightmost leaf. A
naive engine still walks root-to-leaf each time. Production implementations special-case this
"hot rightmost leaf": cache a direct pointer to it, skip traversal for in-order inserts, and fall
back to a full search only when an out-of-order key shows up. Sequential fill also splits purely
rightward, producing denser, more predictable page packing than random insert order — one reason
monotonic primary keys (e.g., Snowflake-style IDs) are recommended for high-insert-rate tables:
less traversal work and less fragmentation.

### Page size / fanout tuning

Page size fixes fanout, and fanout fixes tree height for a given dataset. Bigger pages → more
keys per node → shorter tree, at the cost of reading more bytes per access (even when you needed
one key) and costlier splits/merges (more data copied). The right choice depends on workload and
storage medium — SSDs tolerate larger random reads better than spinning disks, which has nudged
newer engines toward larger pages.

### Copy-on-write vs in-place B-tree updates

Classical engines (InnoDB, SQLite) mutate pages in place and lean on WAL for crash safety.
Copy-on-write variants (LMDB, CoW-filesystem B-trees) never mutate: a change writes a new copy of
the page and of every ancestor up to a new root, which is atomically swapped in; the old tree
stays valid throughout. Crash consistency comes almost for free — a crash mid-update just leaves
the previous root intact — paid for with write amplification, since one leaf edit rewrites an
entire root-to-leaf path.

### Buffer manager duties under transactions

Beyond caching (Part 1), the buffer pool must track dirty pages and enforce the WAL invariant: a
change's log record must be durable before the modified data page may be flushed. This ordering
rule is the load-bearing invariant of crash recovery. Eviction also matters: plain LRU is a
baseline, but production engines use LRU-K, clock-sweep (Postgres), or ARC to survive patterns
like a big sequential scan that would otherwise evict the genuinely hot working set.

### Write-ahead logging

An append-only log records every change — with enough information to both redo it (reapply if the
data page never reached disk) and undo it (reverse it if its transaction never committed) —
before the change touches data pages. Because appends are sequential I/O (fast, per Part 1's
sequential-vs-random discussion), the engine can defer, batch, and reorder the expensive
random-position data-page writes while durability is already guaranteed by the log.

### ARIES-style three-phase crash recovery + checkpointing

On restart: (1) Analysis — scan the log to find transactions in flight and pages dirty at crash
time; (2) Redo — replay the log forward, reapplying everything including work from transactions
that never committed, deliberately: reconstructing the exact physical pre-crash state is a
simpler, more reliable target than selectively replaying only "good" changes; (3) Undo — with
physical state restored, roll back uncommitted transactions using the log's undo records. Because
redo and undo are idempotent and log-driven, the scheme survives crashes at any point, including
during recovery itself. Checkpoints are the optimization layer: periodic log records capturing
live transactions and dirty pages let Analysis start from the latest checkpoint instead of the
log's beginning, bounding recovery time.

### Lock-based concurrency control (2PL and deadlocks)

Transactions take shared locks to read and exclusive locks to write; conflicting requests wait.
Two-phase locking — acquire every needed lock before releasing any — guarantees serializability
at the price of readers and writers blocking each other. The classic failure mode is deadlock
(two transactions each holding what the other needs), handled by detection (cycle search in a
wait-for graph, abort a victim) or prevention (lock-ordering discipline, or wait timeouts).

### Multi-version concurrency control

Instead of blocking, keep multiple versions of each row; every transaction reads a consistent
snapshot as of its start. Readers never block writers and vice versa — a reader just sees an
older version. This is immutability applied at row-version granularity (tying back to Part 1).
Costs: stale versions accumulate and need garbage collection (Postgres vacuum, InnoDB purge), and
write-write conflicts on the same row still require detection, usually resolved by aborting one
contender.

### Isolation levels as an engineering dial

The SQL-standard ladder, weakest to strongest: Read Uncommitted (dirty reads possible; rarely
used), Read Committed (only committed data visible, but a re-read within one transaction may see
a different value — the default in Postgres and many others), Repeatable Read (stable snapshot
for the transaction's duration, though phantoms — newly inserted matching rows — may still appear
depending on implementation), Serializable (equivalent to some one-at-a-time ordering; no
anomalies; most expensive). The level is a real trade-off, not a correctness toggle: stricter
settings cut concurrent-anomaly bugs but cost throughput and raise abort/wait rates under
contention. Knowing which anomalies the application can actually tolerate beats defaulting to
the strictest mode.

## Not absorbed

- Opening greeting and series recap framing ("hey legends", where Part 1 left off) — audience
  rapport, no engineering content beyond what the technical sections restate.
- Closing sign-off and "only one part left" teaser — series promotion.
- View/like/reply counters and timestamp in the capture — platform chrome, not article content.

## Fidelity check

- **Post count in capture:** 1 (a single long-form article post; the JSON reports postCount 1 and
  contains no ---AUTHOR-POST-BREAK--- separators).
- **Article outline (author's own section order):**
  1. Introduction (recap of Part 1, scope of Part 2)
  2. File Formats
     - Binary encoding: general principles
     - Page structure
     - Slotted pages
     - Cell layout
     - Overflow pages
  3. Implementing B-Trees
     - Page header, B-tree specific fields
     - Binary search within a node
     - Insertion and propagating splits
     - Deletion, propagating merges, and rebalancing
     - Right-only appends (the sequential insert optimization)
     - Node size and fanout tuning
     - Copy-on-write versus in-place update variants
  4. Transaction Processing and Recovery
     - Buffer management, revisited
     - Write-ahead logging (WAL)
     - Recovery
     - Concurrency control
     - Isolation levels
  5. Sign-off
- **Pattern → source-section mapping:**
  - Binary on-disk encoding principles ← "Binary encoding: general principles"
  - Fixed-size page anatomy ← "Page structure"
  - Slotted pages ← "Slotted pages"
  - Cell layout ← "Cell layout"
  - Overflow pages ← "Overflow pages"
  - B-tree-specific page metadata ← "Page header, B-tree specific fields"
  - Binary search inside a node ← "Binary search within a node"
  - Insertion with split propagation ← "Insertion and propagating splits"
  - Deletion with borrow/merge ← "Deletion, propagating merges, and rebalancing"
  - Right-only append optimization ← "Right-only appends (the sequential insert optimization)"
  - Page size / fanout tuning ← "Node size and fanout tuning"
  - Copy-on-write vs in-place updates ← "Copy-on-write versus in-place update variants"
  - Buffer manager duties ← "Buffer management, revisited"
  - Write-ahead logging ← "Write-ahead logging (WAL)"
  - ARIES three-phase recovery + checkpointing ← "Recovery"
  - Lock-based concurrency control ← "Concurrency control"
  - Multi-version concurrency control ← "Concurrency control"
  - Isolation levels as an engineering dial ← "Isolation levels"
