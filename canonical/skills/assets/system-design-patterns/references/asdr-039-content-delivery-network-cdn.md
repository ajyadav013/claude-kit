---
source: https://algomaster.io/learn/system-design/content-delivery-network-cdn
author: AlgoMaster.io (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# CDNs as an Edge Cache Layer: Keys, TTLs, Purges, and Origin Protection

## What it teaches

Geographic distance imposes latency no matter how fast the origin server is,
so a CDN moves cacheable responses to edge locations (PoPs) near users and
lets the origin handle only misses, writes, and uncacheable traffic. The
chapter treats a CDN as an engineering surface rather than a checkbox: the
real design work is deciding what is safe to cache in a shared cache, how the
cache key is composed, how freshness is bounded (headers, TTLs, versioned
URLs, purges), how the origin survives synchronized misses, and how to observe
and debug the extra layer. It closes with a provider-selection lens based on
workload fit rather than rankings.

## Key patterns & decisions

- **Edge-first request flow**: DNS points the hostname at the CDN, routing
  picks an edge that is nearby *and* healthy/fast at the network level (not
  merely closest on a map), the edge answers hits locally and fetches misses
  from the origin, storing cacheable responses for later users.
- **Shared-cache safety boundary**: cache static assets and only those dynamic
  responses where every user sharing a cache key should legitimately see the
  same bytes; keep authenticated, personalized, cart/payment/admin responses
  out of shared caches — a cache-key mistake here leaks one user's data to
  another.
- **Cache-key discipline**: the key (scheme/host/path/query, optionally
  selected headers or cookies) defines response identity. Too broad a key
  serves the wrong variant (e.g. ignoring a language header); too narrow a key
  (varying on every cookie) destroys the hit ratio. Normalize query strings
  and exclude cookies unless required.
- **Versioned URLs + long TTLs for immutable assets**: change the URL when the
  content changes, so old copies can stay cached indefinitely and no purge is
  ever needed; reserve short TTLs, targeted purges, cache tags, and
  ETag/Last-Modified revalidation (304 responses) for content that mutates in
  place. Avoid architectures that depend on frequent global purges — they are
  slow, rate-limited, and error-prone mid-incident.
- **Miss-storm protection for the origin**: when a popular object expires
  everywhere at once, use origin shielding (funnel misses through a small
  shield tier), request collapsing (one origin fetch serves many concurrent
  misses), jittered TTLs (desynchronize expirations), and
  stale-while-revalidate (serve slightly old content during background
  refresh).
- **CDN as security front door**: edge platforms bundle DDoS absorption, WAF,
  bot filtering, TLS termination, and rate limiting — reducing what reaches
  the origin, while explicitly not replacing application-level security.
- **Observability per route, not just globally**: expose cache-status debug
  headers, and monitor hit ratio, origin request rate/bandwidth, error rates,
  and purge behavior per path — a healthy global hit ratio can mask one
  expensive, badly-cached endpoint.
- **Provider selection by workload fit**: weigh user geography, cloud
  integration, purge speed and granularity, shielding/collapsing support,
  logs, edge compute, media features, and pricing shape against your traffic —
  e.g. AWS-native teams lean CloudFront, media companies weigh video delivery,
  dynamic-app teams weigh edge logic and purge latency; also check the
  product's lifecycle status.

## When to apply / trade-offs

Apply once users are geographically spread or origin bandwidth/traffic spikes
become costly — static assets, media segments, large downloads, and shareable
API/HTML responses benefit most. The trade is operational: a CDN adds a layer
whose behavior depends on edge location, cache state, headers, and routing,
making debugging harder; staleness becomes a bounded-but-real property of
every cached route (dangerous for prices, permissions, legal text); and
pricing spans bandwidth, requests, purges, and edge features, so media-heavy
workloads need cost modeling. The failure modes worth designing against
up front are cache-key privacy leaks and synchronized-expiry origin overload.

## Fidelity check

1. *Claim*: CDN routing is not purely geographic. The capture states the CDN
   weighs network speed, edge capacity, server health, and configured rules —
   not just map distance — when steering a user to an edge.
2. *Claim*: versioned URLs are the cleanest freshness mechanism for static
   assets. The capture recommends changing the asset URL on content change so
   the old object can remain cached long-term because nothing references it
   anymore, with purges/short TTLs reserved for same-URL content.
3. *Claim*: several named techniques exist to stop expiring hot objects from
   crushing the origin. The capture lists origin shielding, request
   collapsing, jittered TTLs, and stale-while-revalidate specifically as
   mitigations for many edges fetching the same expired object simultaneously.
