---
source: https://algomaster.io/learn/concurrency-interview/design-thread-safe-cache-with-ttl
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Building a concurrent in-memory cache with per-entry expiry

## What it teaches
How to design an in-memory key-value cache where every entry carries its own
expiration deadline, and where reads, writes, and a background reaper can all
run at once without ever handing back stale data or destroying fresh data.
The interesting part is not the map itself but the compound operations layered
on top of it: "check expiry then return value" and "check expiry then delete"
are each two steps, and every race in the design comes from the gap between
those steps.

The chapter walks four named races. First, a TOCTOU stale-read: a reader
validates the deadline, then a reaper deletes the entry before the reader
dereferences the value. Second, a put-versus-cleanup race: the reaper decided
to delete a key based on an old expired entry it saw while iterating, but a
writer replaced that key with fresh data before the delete lands — an
unconditional delete would destroy the new write. Third, plain concurrent
writes to the same key, where last-writer-wins is fine for a cache but fatal
for read-modify-write uses like a rate counter. Fourth, torn reads under weak
memory ordering, where a reader could observe a half-updated entry (new value,
old deadline) because CPUs reorder and buffer stores.

Two design moves dissolve nearly all of these. (1) Make each entry an
immutable value object holding the payload plus an absolute expiry timestamp;
updates create a whole new entry and swap the map reference, so any reference
a reader holds is a consistent snapshot forever. (2) Make every delete
conditional: remove the key only if the map still holds the exact entry you
judged expired, or run the check-and-delete inside the map's per-key atomic
compute so a concurrently written fresh entry is seen and spared.

Three cleanup strategies are compared: one global lock (correct, trivially
serial, throughput-poor); a concurrent map with lazy expiry-on-read only
(great concurrency, but unread dead entries pile up); and the concurrent map
plus a periodic daemon sweeper using conditional removal (adds a scheduler but
bounds memory). Two smaller decisions round it out: store an absolute deadline
computed once at insert (a read becomes one comparison) using a monotonic
clock so NTP or DST jumps cannot make entries expire early or never; and treat
any size() figure as advisory, since the count is stale the instant it is
computed.

## Key patterns & decisions
- Immutable entry objects: value + deadline are frozen at construction, so a held reference can never be observed half-updated; updates replace, never mutate.
- Conditional (compare-and-delete) removal so cleanup only deletes the exact expired entry it observed, never a fresh replacement.
- Per-key atomic compute as the tool for compound check-then-act operations, borrowing the map's internal bucket lock instead of adding an external one.
- Lazy expiry-on-read versus a background sweeper, chosen by whether dead entries are likely to be re-read (lazy suffices) or to linger unread (sweep).
- Absolute monotonic-clock deadlines rather than relative TTLs or wall-clock time, immune to clock steps and cheap to check.
- Daemon-flagged cleanup thread so the reaper never blocks process shutdown.
- Advisory size semantics: counts over a live concurrent structure are for dashboards, never for correctness branching.

## When to apply / trade-offs
Reach for lazy-only expiry when the workload is read-heavy and hot keys get
re-read (session stores, API-response caches); add the sweeper when many
entries die unread and memory pressure matters. The single-global-lock version
is still the right first cut for prototypes and as a correctness oracle to
test optimized versions against. Immutable entries cost an allocation per
write and a small per-entry overhead — negligible for large payloads,
measurable when caching tiny primitives. The lessons generalize: any
"validate then act" pair over shared mutable state is a race until you either
freeze the data or make the pair atomic.

## Fidelity check
- Claim: the reaper must never delete unconditionally because a writer can replace the key mid-sweep. Support: the capture's put-cleanup race walkthrough shows the sweeper queuing "session:abc" for removal from an old expired entry while a writer installs fresh data, and resolves it by an atomic check-and-remove that sees the fresh entry and leaves it.
- Claim: immutability is the chosen fix for both the TOCTOU stale read and torn visibility. Support: the capture states that once a reader holds an entry reference, value and deadline can never change even if the map entry is removed, and that publishing an immutable object through the concurrent map means no reader can see partially constructed fields.
- Claim: the design deliberately uses a monotonic clock for deadlines. Support: the capture argues wall-clock time can jump due to NTP sync or manual adjustment, so expiry is computed against a steadily advancing monotonic source.
