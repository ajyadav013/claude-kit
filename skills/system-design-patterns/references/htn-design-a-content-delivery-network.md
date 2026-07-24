# Digest: Design a Content Delivery Network

- **Source:** https://x.com/Harry_The_Nerd/status/2046578404758295032
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Geographic edge caching (the core CDN premise)
A CDN is a fleet of servers spread across geographies so that content sits physically near the consumer, rather than a single origin far away. The author quantifies the win: a Mumbai user reaching a New York origin pays roughly 200ms round-trip, while a local edge node answers in about 5ms. Use it whenever many users repeatedly fetch identical bytes; the trade-off is operating a distributed fleet plus the entire freshness problem that caching creates.

### Cacheability classification
A simple decision rule for what belongs in a CDN: if every user receives an identical response (HTML, CSS, JS, images, video, fonts, PDFs), it is safe to cache. Four categories must never be cached: (1) per-user data (account balances, private messages) — leaking one user's copy to another is a privacy incident; (2) rapidly changing feeds (live scores, prices, vehicle positions) — the cached copy is obsolete almost immediately; (3) any mutating request (POST/PUT/DELETE) — writes are never cacheable; (4) personalized pages assembled differently per viewer. The mnemonic: identical-for-all ⇒ cache; per-user or per-second ⇒ don't.

### GeoDNS routing
Ordinary DNS hands every resolver the same address. GeoDNS instead inspects where the query originates and answers with the address of the closest edge node, so a Mumbai user is steered to a Mumbai server transparently at the resolution step. The author frames this as the foundation the rest of the design rests on: no application changes are needed, and locality is achieved before the first HTTP byte flows. Trade-off: routing accuracy depends on IP geolocation, and DNS answers must be managed per region.

### Three-tier hierarchy with a regional cache (origin shield)
Naive designs use two tiers (edge → origin), which means every edge miss anywhere in the world lands on the origin independently — misses in Mumbai, Singapore, Dubai, and London each generate their own origin fetch. Production CDNs (the author cites Cloudflare and Akamai) insert a middle tier: a per-region cache that edge misses consult first. Only a miss at that regional layer produces a single origin fetch; every later edge miss in that region is filled from the regional tier. Effect: origin load collapses from thousands of requests to one per object per region.

### Tiered cache-fill request flow
The full read path: GeoDNS picks the edge; an edge hit returns immediately; an edge miss goes to the regional cache; a regional hit returns and also populates the edge; a regional miss goes to the origin, and the response is written into both the regional and edge tiers on the way back. Each miss therefore warms every layer it passed through, so repeat traffic is absorbed as close to the user as possible.

### TTL as the baseline invalidation mechanism
Every cached object carries an expiry; once it lapses, the edge refetches from upstream. This is the default freshness mechanism, but it cannot handle urgent corrections — a long-TTL object stays wrong until it expires.

### Explicit purge for emergencies
A purge broadcasts a delete-now command for a specific object to every edge node worldwide. It gives immediate consistency but is costly precisely because it fans out to thousands of servers, so it should be reserved for critical fixes rather than routine deployments.

### URL versioning (cache busting)
Instead of invalidating, change the object's name — e.g., bump a `?v=` query parameter on an asset URL. The old name keeps serving from cache until its TTL retires it naturally; the new name is a guaranteed miss and thus immediately fresh. No purge traffic at all. The author notes this is the standard production approach for frontend assets.

### Cache-Control header vocabulary
The origin declares caching policy per object via response headers, and the CDN plus browser obey. Key directives restated: `max-age` sets the TTL in seconds; `no-store` forbids caching entirely (checkout pages, sensitive endpoints); `private` allows the browser to cache but not any shared/CDN cache (per-user data); `s-maxage` sets a CDN-specific TTL that overrides `max-age`, letting the shared cache and the browser hold different lifetimes (e.g., a trending feed cached 300s at the CDN). Illustrative policies from the article: a logo cached publicly for a year (max-age=31536000) versus a user watchlist marked private/no-store.

### Storage tiering matched to speed-vs-capacity
Each tier's storage medium mirrors its role: edge nodes use in-memory storage (Redis, ~100GB per node) — fastest, smallest, only that city's hottest objects; regional caches use SSDs (~10TB per node) — slower but roomy enough for a continent's warm set; the origin uses object storage (S3) with effectively unlimited capacity as the permanent source of truth. A separate metadata store (Cassandra) holds TTL rules, cache policies, and per-object cache status that edge nodes consult to decide retention.

### Independent edges for horizontal scalability
Capacity grows by adding edge nodes in new cities; because edges never coordinate with each other, there is no cross-node consensus cost, and the regional tier soaks up the miss traffic that would otherwise make origin load scale with edge count. This makes edge fan-out essentially linear.

### Graceful degradation across tiers
Failure handling is layered fallback: if an edge dies, GeoDNS steers users to the next-nearest edge; if a regional cache dies, edges skip it and fetch straight from the origin — slower, but the service stays up. Every tier has a defined slower-but-working path rather than a hard failure mode.

## Not absorbed

- Series branding ("High-Level Design Questions-Based Series #6") — interview-prep framing, not engineering content.
- The "most people design it as two tiers" contrast — rhetorical setup for the origin-shield section; the substance is captured in the three-tier pattern above.
- Sign-off line ("Thats all folks...Cheers!") and engagement metrics (views/likes/reposts) — social wrapper.
- Conversational color ("caching thingie", "the Og source of truth", "core magic") — tone, not substance.

## Fidelity check

- **Post count in capture:** 1 (single long-form post; JSON `postCount: 1`, no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline as authored:**
  1. Intro — why a CDN exists (200ms vs 5ms latency framing)
  2. Functional requirements
  3. What to cache and what not to
  4. Geographic routing (GeoDNS)
  5. The three-tier architecture (including the complete request flow)
  6. Cache invalidation: keeping the content fresh (TTL → Purge → Versioning → Cache-Control headers)
  7. The data layer
  8. Non-functional requirements (Latency, Scalability, Availability)
  9. Sign-off
- **Pattern-to-section citations:**
  - Geographic edge caching — Intro + Functional requirements
  - Cacheability classification — "What to cache and what not to"
  - GeoDNS routing — "Geographic routing (GeoDNS)"
  - Three-tier hierarchy / origin shield — "The three-tier architecture"
  - Tiered cache-fill request flow — "The three-tier architecture" (complete request flow diagram)
  - TTL baseline invalidation — "Cache invalidation" (TTL paragraph)
  - Explicit purge — "Cache invalidation" (Purge subsection)
  - URL versioning — "Cache invalidation" (Versioning subsection)
  - Cache-Control header vocabulary — "Cache invalidation" (Cache-Control headers subsection)
  - Storage tiering — "Now, The data layer"
  - Independent edges for scalability — Non-functional requirements (Scalability)
  - Graceful degradation — Non-functional requirements (Availability)
