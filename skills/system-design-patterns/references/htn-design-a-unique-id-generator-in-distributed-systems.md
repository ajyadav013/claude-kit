# Digest: Design A Unique ID Generator in Distributed Systems

- **Source:** https://x.com/Harry_The_Nerd/status/2057461354114728238
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Requirements checklist for a distributed ID scheme

Before picking a generator, the article pins down five properties a production-grade
distributed ID must satisfy: uniqueness across every node with no exceptions;
time-sortability (comparing two IDs tells you which was created first); a numeric
representation so databases and indexes stay efficient; throughput in the
thousands-of-IDs-per-second range; and low enough latency that generation never
becomes the bottleneck on the write path. **When to use:** treat this as the rubric
against which any candidate scheme is scored — it is what turns "pick an ID format"
into an actual design decision. **Trade-off:** no scheme maxes out every axis; the
rest of the article is the exercise of trading them against each other.

### Anti-pattern — the single auto-increment column

A lone database with an auto-incrementing primary key is the naive baseline, and the
article dissects exactly why it dies at scale: (1) it is a single point of failure —
if that box is down, no new records can be created anywhere; (2) it is a throughput
ceiling, since every write in the system must round-trip through one machine; and
(3) it cannot be horizontally scaled, because a second node handing out the same
counter values immediately produces collisions. The deeper insight: the centralized
sequential state that makes auto-increment correct is precisely the property that
makes it unusable once the system is distributed. **When to use:** single-server
systems only — where it remains the simplest correct answer.

### Multi-master replication (interleaved step-and-offset counters)

Run k database servers, each with its own auto-increment counter, but configure every
server to step by k rather than 1 and to start from a distinct offset. With k=3 the
servers emit 1,4,7,…; 2,5,8,…; and 3,6,9,… — the sequences interleave by construction
so collisions are impossible without any runtime coordination. **When to use:** a
small, fixed-size cluster that needs numeric IDs and can live without global time
ordering. **Trade-offs:** elasticity is the killer — adding a node later means
reconfiguring the step on every existing server, a risky live operation; IDs are not
time-ordered across servers (one node can be far ahead of another numerically while
behind in wall-clock time); and the fixed-node assumption makes it brittle across
data centers or regions.

### UUID (v4) — coordination-free random IDs

Each machine independently mints 128-bit identifiers; v4 fills the bits with
randomness, so there is no central authority, no network call, and no shared state
of any kind. **When to use:** when uniqueness and operational simplicity dominate
and ordering does not matter. **Trade-offs:** 128 bits is twice the storage and
index cost of the 64-bit IDs many systems prefer; random values carry no time
information, breaking time-range queries and log reasoning; randomness is actively
hostile to B-tree indexes (monotonic keys append cleanly, random keys cause page
splits and fragmentation, eroding write throughput over time); and the usual hex
string form is awkward for integer-expecting downstream systems.

### Ticket server — a dedicated centralized ID authority

One purpose-built service owns a single auto-increment counter and every other
service fetches IDs from it over the network (the article cites Flickr as the
well-known adopter). The payoff is clean sequential numeric IDs with zero collision
risk and a trivially simple implementation. **When to use:** modest scale with a
hard requirement for strict sequences. **Trade-offs:** it reintroduces the single
point of failure — and running multiple ticket servers just brings back the
inter-server dedup coordination problem you were trying to escape; every ID now
costs a network round trip, which compounds at high volume; and vertical scaling of
one machine puts a hard cap on system-wide write throughput.

### Snowflake — 64-bit composite IDs generated locally

Twitter's scheme packs four fields into one 64-bit integer: a sign bit held at 0 to
keep values positive; 41 bits of milliseconds since a custom epoch (roughly 69 years
of headroom); 10 bits of machine ID (1,024 distinct nodes); and a 12-bit per-node
sequence counter that resets each millisecond (4,096 IDs per node per millisecond).
Because the timestamp occupies the high bits, IDs sort by creation time for free,
and because everything is computed in local memory there are no network calls or
cross-node coordination on the hot path. **When to use:** the article's default
recommendation for large-scale distributed systems — high throughput, time-sorted,
numeric, horizontally scalable. **Trade-offs:** correctness depends on the system
clock — a backward NTP correction can mint duplicates or past-dated IDs, so you need
drift detection plus a wait strategy; unique machine IDs must be assigned across the
fleet, typically via ZooKeeper or similar, which adds operational surface; ordering
is only per-node monotonic — same-millisecond IDs from different machines interleave
by machine ID, not by true event order; and the 41-bit timestamp overflows about 69
years after the epoch, a real consideration only for very long-lived systems.

### Decision matrix — scoring schemes against the requirements

The article closes the technical argument with a five-axis comparison (unique /
time-sorted / no single point of failure / high throughput / easy to scale) applied
to all five schemes. Snowflake is the only one that clears every axis; UUID clears
all but time-sorting; multi-master fails ordering and elasticity; ticket server and
plain auto-increment fail availability and throughput. The concluding guidance:
Snowflake (or a variant) is the default for large systems because its remaining
weaknesses (clock trust, machine-ID assignment) are well-understood and fixable —
but UUIDs win on simplicity when ordering is irrelevant, and a ticket server is
legitimate for a small fixed cluster needing strict sequences. Knowing each
scheme's failure modes is what distinguishes a design that survives 100k RPS from
one that only works at 100.

## Not absorbed

- Series branding ("High-Level Design Questions-Based Series #11") — interview-prep framing, not engineering content.
- Sign-off line ("That's all folks…") — conversational closer.
- Post metadata (timestamp, view/like/reply counts) — platform chrome, not article content.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; `postCount: 1` in the JSON, no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline (as the author structured it):**
  1. Introduction — why entities need IDs and why distribution breaks the trivial answer
  2. Requirements for a good distributed unique ID (five-bullet list)
  3. Why Single Auto-Increment Fails
  4. The Four Major Approaches
     1. Multi-Master Replication
     2. UUID (Universally Unique Identifier)
     3. Ticket Server
     4. Twitter's Snowflake
  5. Comparison at a Glance (five-axis table)
  6. Closing guidance — Snowflake as default, constraint-dependent exceptions
- **Pattern-to-section citations:**
  - Requirements checklist → section 2 (requirements list)
  - Anti-pattern: single auto-increment → section 3 ("Why Single Auto-Increment Fails")
  - Multi-master replication → section 4.1
  - UUID (v4) → section 4.2
  - Ticket server → section 4.3
  - Snowflake → section 4.4
  - Decision matrix → sections 5 ("Comparison at a Glance") and 6 (closing guidance)
