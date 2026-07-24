# Design Consistent Hashing — digest

- **Source:** https://x.com/Harry_The_Nerd/status/2057098732328648808
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Modulo hashing (baseline key-to-node routing)

Pick a node with `hash(k) mod N` where N is the server count. Every client computes the owner independently — no coordination service, no lookup table, constant-time and trivial to implement. Use it only when the node set is genuinely fixed (or remaps are cheap, e.g., stateless routing). Its hidden assumption is that N never changes; the moment membership is dynamic, this scheme becomes the liability described next.

### The rehashing / cold-cache stampede failure mode

When N changes (a node is added, or one dies), the modulo formula reassigns almost every key: roughly (N−1)/N of all keys land on a different node. For a cache tier this means the cluster is effectively wiped in one instant — every request misses and falls through to the database at once, a stampede that can cascade into a full outage. The takeaway is an anti-pattern check: any placement scheme that bakes the cluster size into the hash treats failures (which are inevitable) as remap-everything events. Design for membership churn as a normal operation, not an exception.

### Consistent hashing on a ring

Map servers and keys into the same circular hash space (a number line from 0 to 2^32−1 that wraps around). Each server is hashed by an identifier (IP/hostname/ID) to a ring position; each key is hashed to its own position; the key's owner is the first server encountered walking clockwise. Implement lookup with a sorted array or balanced BST of server positions — a binary search resolves ownership in O(log N).

The payoff is locality of change: adding a server claims only the arc between it and its counterclockwise predecessor; removing a server hands its arc to the next clockwise node. With K keys and N servers, roughly K/N keys move on any membership change, versus the near-total remap of modulo hashing. All other nodes are untouched.

Trade-offs of the *basic* form: server positions come from hashing a handful of names, so arcs are wildly uneven (one node can own half the ring while another owns a sliver), a failed node dumps its entire arc onto exactly one clockwise neighbor (risking a domino of overloads), and there is no way to give a bigger machine a bigger share. These are predictable outcomes of placing few points on a ring, not rare edge cases.

### Virtual nodes (vnodes)

Place each physical server on the ring many times by hashing derived identifiers (e.g., the server name suffixed with an index: name#1, name#2, …). A common operating point is 100–200 vnodes per physical machine. Each physical server then owns many small scattered arcs whose total sizes average out, which fixes the basic ring's problems:

- **Even load:** aggregate ownership per machine converges to roughly equal shares even with few physical nodes.
- **Graceful failure:** a dead server's ~150 scattered positions are absorbed by many different physical neighbors, so its load is spread thin instead of doubling one victim's traffic.
- **Smoother scale-out:** a joining node with many vnodes takes small slices from many existing nodes rather than one big arc from a single neighbor.

Trade-off: the ring's position index grows by the vnode multiplier (more entries to search and more metadata to keep in sync), which is why vnode counts are tuned rather than made arbitrarily large.

### Capacity-weighted placement via vnode count

Heterogeneous fleets fall out of the vnode mechanism for free: assign vnode counts proportional to machine capacity. A box with twice the RAM/CPU gets twice the vnodes and therefore attracts roughly twice the keys. This is the standard way to express weights in a consistent-hash layer without any separate weighting logic.

### Where the pattern shows up in production

- **Partitioned datastores:** DynamoDB and Cassandra shard data this way; Cassandra's token ring is a direct implementation, vnodes included.
- **CDNs:** request-to-edge-node routing is decided deterministically by consistent hashing, with no central lookup table.
- **Load balancers:** sticky sessions survive backend scale-up/down with minimal reshuffling because only the affected arcs remap.

The meta-lesson the article closes on: modulo → consistent hashing → vnodes is a case study in how each design is adequate until scale breaks one of its assumptions, and the successor targets exactly that failure mode.

## Not absorbed

- Series branding ("High-Level Design Questions-Based Series #10") — interview-prep framing, not engineering content.
- "Here's what the math looks like:" — points at an inline figure that the text capture does not contain; no substance to summarize.
- Sign-off line ("That's all folks…") — pleasantry.
- Trailing engagement counters (views/replies/reposts/likes) — platform chrome captured with the post text.

## Fidelity check

- **Post count in capture:** 1 (a single long-form article post; `postCount: 1` in the JSON, no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline (author's own section order):**
  1. What is hashing in distributed systems? (modulo hashing intro)
  2. The Rehashing Problem
  3. Consistent Hashing: The Idea
  4. How Consistent Hashing Solves Rehashing
  5. The Problem with Basic Consistent Hashing
  6. Virtual Nodes: The Fix
  7. Where You'll See This in the Wild
  8. Closing progression recap + sign-off
- **Pattern → section mapping:**
  - Modulo hashing (baseline) → section 1 ("What is hashing in distributed systems?")
  - Rehashing / cold-cache stampede failure mode → section 2 ("The Rehashing Problem")
  - Consistent hashing on a ring → sections 3–4 ("Consistent Hashing: The Idea", "How Consistent Hashing Solves Rehashing"); its listed weaknesses → section 5 ("The Problem with Basic Consistent Hashing")
  - Virtual nodes → section 6 ("Virtual Nodes: The Fix")
  - Capacity-weighted placement via vnodes → section 6 (the proportional-capacity bullet)
  - Production usage examples → section 7 ("Where You'll See This in the Wild"); the meta-lesson → section 8 (closing)
