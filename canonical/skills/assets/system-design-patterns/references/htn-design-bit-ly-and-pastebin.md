# Design Bit.ly and Pastebin — engineering digest

- **Source:** https://x.com/Harry_The_Nerd/status/2044672371546877964
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Read/write asymmetry as the primary design driver
Both systems are characterized as read-dominated: a short link or paste is written once and then
served many times. The article treats this single observation as the root cause of most downstream
choices — caching layers, read replicas, and splitting the service into separate read and write
components. Use this framing whenever one operation type dwarfs the other; the trade-off is extra
moving parts in exchange for scaling each path independently.

### Back-of-envelope capacity math with rounded constants
The worked estimate assumes 10M daily active users and 1B URLs over the system lifetime, and rounds
a day to 100k seconds to keep the arithmetic mental-math friendly. That yields roughly 10,000
requests/second overall, which is then split by the read/write ratio: writes at about 1% (~100
req/s) and reads at ~99% (~9,900 req/s). The technique's point is not precision but deriving the
order of magnitude and the ratio, because those two numbers decide which scaling machinery is even
worth discussing.

### Base62 of a monotonic ID instead of truncated hashes
A common pitfall the article calls out: hashing the long URL (MD5/SHA-256) and keeping only the
first 6 characters, which invites prefix collisions between distinct inputs. The recommended
alternative is Base62-encoding an auto-incrementing numeric ID — uniqueness of the ID transfers
directly to the encoded key, so no collision detection or retry loop is needed. The alphabet is
digits plus lower- and upper-case letters (10+26+26 = 62), and 6 characters give a keyspace of
about 56 billion. Trade-off (implicit): sequential IDs are guessable and require a central
ID source, but the article prioritizes simplicity and collision-freedom.

### Splitting write and read services behind a gateway
The proposed topology is client → API gateway → two independent services → database. For Bit.ly:
a shortener service owns writes (mint the Base62 key, persist the mapping) and a redirector
service owns reads (look up the key, return the target). Pastebin mirrors this with a write
service (upload content, persist metadata) and a read service (fetch metadata, then content).
The benefit is that the high-volume read path can be scaled and cached without touching the
low-volume write path.

### Layered read-scaling hierarchy: cache → replicas → shard last
Reads are scaled in a strict order. First, Redis with LRU eviction — justified by a Pareto-style
observation that roughly 20% of links attract 80% of traffic, so LRU organically retains the hot
set; a TTL is layered on top of eviction. Second, cache misses are absorbed by database read
replicas. Sharding the primary database is deliberately last, reserved for when write volume
itself becomes the bottleneck. The explicit anti-pattern is reaching for sharding prematurely.

### Minimal key-value schema; SQL is enough for lookup workloads
The URL table is small: a unique ID, the short key, the target URL, the creating user, and a
creation timestamp. Because access is pure point lookups with no joins, a relational database is
perfectly adequate; the article notes Cassandra as a very-large-scale alternative, with the caveat
that everything must live in one denormalized table since it lacks join support. The lesson:
match the store to the query shape rather than defaulting to a "web-scale" database.

### Metadata/blob separation (DB pointer + object storage)
The core architectural difference for Pastebin: never store the text payload in the relational
database, because large blobs degrade DB performance. Instead, storage is split into two layers —
the database keeps only metadata (user, short key, an object-storage URL, created/expiry
timestamps) while the actual content lives in object storage such as S3. The DB row is a pointer,
keeping the database small and fast; the read path becomes a two-hop fetch (metadata, then blob).

### Expiry as a first-class schema field plus a cleanup job
Pastebin links are time-limited, so the schema carries an expires_at column and the design includes
a background job that purges expired entries from both the database and the object store. The
notable engineering point is the dual-store cleanup — deleting the metadata row without the S3
object (or vice versa) would leak storage or dangle pointers, so expiry must be enforced
consistently across both layers.

## Not absorbed

- Series kickoff and greeting ("High-Level Design Question series #1", audience address) — promotional
  framing for a post series, no design content.
- The five-step interview answer structure (functional reqs → NFRs → math → HLD → deep dives) —
  interview-prep meta about how to present, not a system technique in itself.
- Remarks about what interviewers want to see and which details "signal" product thinking —
  interview-audience framing.
- The note that analytics is usually optional in interviews — scoping advice for interviews, not a
  design decision.
- Closing call to share the post — promotion.
- Trailing engagement metrics (views/likes counts, timestamp) — capture artifact, not article content.

## Fidelity check

- **Post count in capture:** 1 (a single long-form article post; `postCount: 1` in the JSON, no
  `---AUTHOR-POST-BREAK---` separators present).

### Article outline (as authored)

1. Intro — series announcement; Bit.ly and Pastebin look similar but differ architecturally
2. Designing Bit.ly — the URL shortener
3. The structure interviewers want to see (5-step framework)
4. Functional requirements for Bit.ly
5. Nature of the system (read-heavy)
6. Back-of-envelope
7. The short link generation (hash-prefix mistake; Base62 of an auto-incremented ID)
8. Architecture (client → gateway → shortener + redirector services → DB)
9. Caching & scaling reads (Redis LRU, read replicas, sharding last)
10. DB schema (+ SQL vs Cassandra note)
11. Designing Pastebin — functional requirements
12. Nature of the system (read-heavy, same caching approach)
13. The key difference from Bit.ly is content storage (DB metadata + S3 blob)
14. Architecture (write service / read service over DB + S3)
15. Expiry (expires_at + cleanup job across DB and S3)
16. Outro — closing thanks and share ask

### Pattern-to-section citations

| Pattern | Source section |
|---|---|
| Read/write asymmetry as the primary design driver | "Nature of the system" (Bit.ly, section 5) and "Nature of the system" (Pastebin, section 12) |
| Back-of-envelope capacity math with rounded constants | "Back-of-envelope" (section 6) |
| Base62 of a monotonic ID instead of truncated hashes | "Now, the short link generation" (section 7) |
| Splitting write and read services behind a gateway | Bit.ly "Architecture" (section 8) and Pastebin "Architecture" (section 14) |
| Layered read-scaling hierarchy: cache → replicas → shard last | "Caching & scaling reads" (section 9) |
| Minimal key-value schema; SQL is enough for lookup workloads | "DB schema" (section 10) |
| Metadata/blob separation (DB pointer + object storage) | "The key difference from Bit.ly is content storage" (section 13) |
| Expiry as a first-class schema field plus a cleanup job | "Expiry (imp here)" (section 15) |
