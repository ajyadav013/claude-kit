---
source: https://blog.algomaster.io/p/how-dns-actually-works
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# DNS resolution as a layered cache-and-delegate hierarchy

## What it teaches

How a human-readable hostname becomes a routable IP address, and why that
translation is fast and dependable at planetary scale. The core mental model is
a chain of caches backed by a delegation hierarchy: the answer is looked for in
the cheapest place first (browser memory, then the OS-level cache shared by all
programs on the machine), and only if every local layer misses does the query
leave the machine for a recursive resolver — typically run by the ISP or a
public operator such as Google (8.8.8.8) or Cloudflare (1.1.1.1). The resolver
then walks the naming hierarchy top-down: a root server (13 logical identities,
replicated in hundreds of physical sites) points it at the server family for
the domain's suffix (the TLD tier, e.g. everything ending in .com), which in
turn points at the domain's own authoritative name server — the single source
of truth that finally returns the address record. The result is cached at each
hop on the way back, so the multi-step walk is the rare case, not the common
one. The whole round trip completes in milliseconds.

The article also explains that authoritative servers hold multiple record
kinds, not just addresses: IPv4 vs IPv6 address records, alias records, mail
routing records, and free-text records used for ownership verification — and
that a single name can carry several addresses at once for failover and
traffic spreading.

## Key patterns & decisions

- **Hierarchical delegation over a flat directory**: no single server knows
  every name; each tier only knows who to ask next, which bounds any one
  server's dataset and blast radius.
- **Multi-layer caching (browser → OS → resolver)**: each layer absorbs repeat
  lookups so the expensive full walk is amortized to near zero.
- **Recursive resolver as the client's delegate**: the client asks one server
  a single question; that server takes on the whole iterative hunt and returns
  either an answer or a definitive "does not exist."
- **Anycast for latency and resilience**: root servers and public resolvers
  advertise one IP from many geographic sites, so queries land at the nearest
  healthy replica automatically.
- **Redundant authoritative servers across regions**: a domain publishes
  several name servers so the loss of one does not make the domain
  unresolvable.
- **GeoDNS**: answering the same name with different addresses depending on
  the asker's location, for proximity routing or data-residency compliance.
- **DNS-level load balancing**: returning several address records for one
  name spreads client connections across a server pool with no extra
  infrastructure.
- **CDN steering via DNS**: resolving a name to a nearby edge node is the
  mechanism by which CDNs place static content close to users.

## When to apply / trade-offs

Reach for these ideas whenever you design any name-to-endpoint indirection
(service discovery, tenant routing, region failover): the cache-hierarchy +
delegation pattern generalizes well beyond DNS itself. Trade-offs the article
implies: caching trades freshness for speed (a cached answer can be stale
until it expires), DNS round-robin is a crude balancer with no health
awareness of its own, and GeoDNS answers depend on where the *resolver* sits,
which may not match the end user. The delegation chain also means resolution
latency is worst exactly when caches are cold.

## Fidelity check

1. *Claim*: local caches are consulted before any network query. — *Capture
   support*: the resolution walkthrough starts with the browser checking its
   own recent lookups, then falls back to an OS-maintained cache shared across
   applications, and only then sends the query to a recursive resolver.
2. *Claim*: root servers never return the final address; they only redirect.
   — *Capture support*: the article states root servers examine the domain
   suffix and hand the resolver on to the matching TLD tier, explicitly noting
   they do not hold the final IP.
3. *Claim*: there are 13 root server identities but far more physical
   instances. — *Capture support*: the article says only 13 sets of root
   servers exist globally while being replicated in hundreds of locations for
   reliability.
