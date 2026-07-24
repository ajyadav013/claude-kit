# system-design-patterns

Reusable high-level-design building blocks for the whiteboard/HLD stage — before any code exists.

## What this covers

- **Back-of-envelope estimation**: rounded-constant math (day ≈ 100k s) and letting the read/write ratio drive the architecture
- **Rate limiting**: token/leaky bucket, fixed/sliding window, edge enforcement, fail-open vs fail-closed
- **Load balancing**: L4 vs L7, five algorithms, dual health checks, the statelessness prerequisite
- **CDN & edge**: cacheability rule, origin shield, TTL/purge/versioning, push vs pull placement
- **Caching hierarchy**: power-law selective caching, L1/L2/L3 hot-key defusal, precompute-and-serve, ID-then-hydrate
- **Unique IDs**: Base62 of a monotonic ID vs truncated hashes; Snowflake-style 64-bit composites
- **Fan-out**: notification channel routing with retry/fallback ladders; push/pull/hybrid news feeds; typeahead precompute; chat store-and-forward
- **Data modeling**: metadata/blob separation, first-class expiry, two-phase expiring holds, calendar-table inventory
- **Service boundaries**: the four-criteria microservice test, the cost ledger, Conway's Law
- **Composite map**: a table mapping 16 worked system designs (Twitter, Amazon, Netflix, Airbnb, chat, feeds, …) to the blocks they compose

## Origin

Own-words digests of public X threads by Harshit Khosla ([@Harry_The_Nerd](https://x.com/Harry_The_Nerd)) — 24 system-design walkthroughs captured under `references/htn-*.md`, synthesized here in the kit's voice with no verbatim text. Concrete numbers and algorithm parameters are restated as facts.

## Structure

- `SKILL.md` — the building blocks, anti-patterns, composite map, and cross-links
- `references/htn-*.md` — the 24 per-thread digests, each with a fidelity check and pattern-to-section citations

## Usage

Read this skill when designing or reviewing a system architecture: sizing a workload, choosing rate-limiting/balancing/caching machinery, picking an ID scheme, designing fan-out, or judging a service split. Runtime failure discipline (retries, circuit breakers, backpressure) stays with `rules/resilience-engineering.md`; state distribution with `distributed-systems-patterns`.
