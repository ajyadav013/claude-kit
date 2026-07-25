---
source: https://blog.algomaster.io/p/rest-vs-graphql
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Choosing between REST and GraphQL by data-shape needs

## What it teaches

The article compares the two dominant API philosophies. REST (early 2000s) is
a set of conventions layered on plain HTTP: each domain resource gets a URL,
and a fixed verb set (GET/POST/PUT/PATCH/DELETE) manipulates it, with standard
status codes signaling outcomes. Its strengths are the intuitive resource
model, statelessness (every request self-contained, which aids horizontal
scaling), free use of HTTP/CDN/browser caching, and two decades of tooling and
developer familiarity. Its recurring pains: over-fetching (fixed endpoints
return fields the client doesn't want), under-fetching (related data forces a
chain of follow-up requests, e.g. one call for a user and another for that
user's posts), URL-based versioning overhead when the API evolves, and a
server-dictated response shape clients must adapt to.

GraphQL (Facebook, 2015) inverts control: one endpoint accepts client-authored
queries against a strongly typed schema, returning exactly the requested
fields — killing both over- and under-fetching in a single round trip that can
span multiple backend sources. Its three operation kinds map to needs: queries
read, mutations write, and subscriptions push real-time updates without
client polling. Schema-first typing gives self-documenting, explorable APIs,
and additive field evolution avoids v1/v2 URL churn. The costs are real:
heavier setup (server, schema, resolvers versus curl-able REST), broken HTTP
caching because queries typically travel as POSTs, and — the article's
sharpest warning — a performance/security exposure unique to client-authored
queries: since clients compose queries, a deeply nested or unbounded request
can translate into a catastrophic database scan, effectively letting one
client feature take down a shared database. Defenses (query depth limits,
cost analysis, rate limiting) are mandatory complexity that REST's predefined
endpoints simply don't need.

The verdict is need-based, not winner-based, and explicitly endorses hybrids:
GraphQL facing product clients with diverse data needs, REST for admin
surfaces, third-party integrations, and internal service calls where caching
and simplicity dominate.

## Key patterns & decisions

- Over-fetching/under-fetching as the diagnostic pair: fixed REST responses waste bandwidth on unwanted fields, while missing related data multiplies round trips — GraphQL exists to fix exactly these two.
- Control inversion: REST lets the server define response shape; GraphQL lets the client compose it — flexibility bought at the price of server-side unpredictability.
- Schema as contract: GraphQL's strict typed schema makes APIs explorable and self-documenting, versus REST's looser, sometimes version-drifting responses.
- Additive evolution over URL versioning: add fields without breaking existing queries instead of maintaining /v1 and /v2 trees.
- Subscriptions for push: native real-time updates replace polling or hand-rolled WebSocket layers for chat/feeds/notifications use cases.
- Query cost as an attack/outage surface: client-composed queries demand depth limits, cost analysis, and rate limiting or a single bad query can trigger full-table scans (DoS-adjacent risk).
- Caching asymmetry: REST rides browser/CDN/HTTP caching for free; GraphQL's POST-based queries make edge caching materially harder.
- Hybrid architecture as a legitimate end state: GraphQL for flexible client-facing reads, REST where statelessness, cacheability, and third-party familiarity win.

## When to apply / trade-offs

Pick REST when the API is simple, cache-heavy, third-party-facing, or the team
needs speed with familiar tooling. Pick GraphQL when many client types need
different slices of deeply connected data, when real-time subscriptions are
core, or when versioning churn is a proven pain. The hidden cost of GraphQL is
operational: resolver optimization, query-cost policing, and cache
workarounds are ongoing engineering, not one-time setup. The article's framing
("which is better for your needs") is sound but interview-oriented breadth —
it does not cover persisted queries or federation, which production GraphQL
teams usually reach for.

## Fidelity check

1. Claim: under-fetching means chained requests for related data. Support: the capture illustrates needing one call to fetch a user and a second call to fetch that user's posts when the first endpoint doesn't embed them.
2. Claim: GraphQL's flexibility creates a database-load risk REST largely avoids. Support: the capture describes a mobile feature whose client-built query inadvertently triggers a full table scan, noting REST's predefined endpoints make this scenario less likely and that GraphQL needs rate limiting, depth restrictions, and cost analysis in response.
3. Claim: the article endorses running both styles together. Support: the capture's closing section says the approaches aren't mutually exclusive and sketches a hybrid — GraphQL for client-facing apps, REST for admin interfaces, third-party integrations, and internal microservices.
