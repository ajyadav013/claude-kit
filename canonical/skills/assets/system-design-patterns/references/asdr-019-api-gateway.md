---
source: https://blog.algomaster.io/p/what-is-an-api-gateway
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# API gateway: one front door for a microservice fleet

## What it teaches

An API gateway is a single server positioned between all clients (browsers,
mobile apps) and the backend service fleet. Its justification is subtraction:
without it, every client must know where each microservice lives, and every
service team must re-implement authentication, rate limiting, and hardening
independently. With it, clients hit one address and the cross-cutting
operational concerns are enforced once, centrally.

The article enumerates eight core gateway capabilities. Identity work comes
first: verifying who the caller is (tokens, keys, certificates) and whether
they may perform the operation, centralized so individual services can drop
that duplication and access control stays consistent. Rate limiting caps
per-client request frequency inside a time window to keep abusive or runaway
traffic from swamping backends. Load balancing spreads requests across healthy
instances using strategies like round-robin, least-connections, or weighted
distribution, steering around dead or saturated nodes. Caching holds hot
responses and static assets at the edge to cut latency and backend load.
Request/response transformation reshapes payloads between what clients send and
what services expect — the classic case being a legacy XML service fronted with
JSON. Service discovery resolves which live instance should receive a request
in an environment where instances scale up and down constantly. Circuit
breaking watches backend health signals (timeouts, 5xx responses, latency
spikes) and temporarily stops forwarding traffic to a persistently failing
service. Logging and metrics collection at the gateway give a single vantage
point for request rates, error rates, and latency, feeding tools in the
Prometheus/Grafana/CloudWatch family.

The second half walks one food-delivery order request through the gateway's
processing sequence: receive the request at the single entry point; validate
structure, headers, and schema (rejecting early with a clear error); verify
identity against an identity provider and check permissions (401/403 on
failure); consult per-user rate counters (429 when exceeded); transform data
the downstream needs in a different shape (street address to coordinates for
a delivery service); fan out via discovery plus load balancing to the order,
inventory, payment, and delivery services; reshape and optionally cache the
combined response; and record timing/status metrics throughout.

## Key patterns & decisions

- Single entry point: clients address one gateway instead of discovering N services, decoupling client configuration from backend topology.
- Centralize cross-cutting concerns (authn/authz, rate limits, logging) at the edge once, rather than duplicating them per microservice.
- Fail fast at the edge: structural/schema validation before any backend work, so malformed requests never consume service capacity.
- Ordered request pipeline: validate → authenticate/authorize → rate-limit → transform → route — cheap and security-critical checks precede expensive fan-out.
- Windowed per-user rate counters (increment a keyed counter with an expiry) returning 429 past the threshold, protecting stability during spikes and DoS attempts.
- Circuit breaking on observed backend health (timeouts, server errors, latency) to shed traffic from failing services and let them recover.
- Gateway-level transformation as an adapter layer: format conversions and enrichment (e.g., geocoding an address) so clients and services can evolve independently.
- Discovery-plus-load-balancing routing so requests reach healthy instances even as the fleet autoscales.
- Edge caching of frequently requested responses to trade freshness for latency and backend cost.

## When to apply / trade-offs

A gateway earns its keep once there are multiple services and multiple client
types; for a single monolith it mostly adds a hop and an operational component
to run. The centralization is double-edged: it removes duplicated auth logic
but creates a critical single point that must itself be scaled and monitored
(the article positions it on every request path). Transformation at the edge
is convenient but can quietly accumulate business logic that belongs in
services. The article is introductory — it does not weigh gateway products
against each other or discuss gateway HA — so treat it as the concept map, not
a deployment guide.

## Fidelity check

1. Claim: the gateway rejects invalid requests before touching backends. Support: the capture's step-by-step walkthrough puts structure/header/format validation immediately after receipt, with an immediate error back to the app when something is missing or malformed.
2. Claim: rate limiting is implemented as a per-user counter in a time window. Support: the capture's example tracks recent order requests per user, allows ten per minute, and answers over-limit traffic with a 429 response.
3. Claim: circuit breaking triggers on persistent backend failure signals. Support: the capture lists slow responses/timeouts, HTTP 500-class errors, and high latency or unavailability as the conditions under which the gateway stops sending requests to a service it monitors.
