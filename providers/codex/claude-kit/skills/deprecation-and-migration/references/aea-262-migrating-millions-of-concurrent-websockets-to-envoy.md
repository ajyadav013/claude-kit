---
source: https://slack.engineering/migrating-millions-of-concurrent-websockets-to-envoy/
author: Slack Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Zero-downtime replacement of a live load-balancer tier (Slack's HAProxy-to-Envoy websocket move)

## What it teaches

Slack terminated millions of long-lived websocket connections on a dedicated
HAProxy fleet. HAProxy's operational model became the pain point: every change
to a backend endpoint list required either the runtime API (which had burned
them before) or a config re-render plus reload, and each reload spawned a new
process while old processes lingered for hours draining long-lived
connections. They needed extra machinery just to reap stale processes and
rate-limit reloads. Envoy removed that whole problem class: dynamically
discovered clusters/endpoints need no reload, and a true hot restart carries
connections and even stats counters across, so no side-car babysitting
infrastructure is needed. Bonus capabilities — zone-aware routing, passive
health checks via outlier detection, and panic routing (deliberately routing
to "unhealthy" hosts when the healthy fraction collapses, which saved them
during a January 2021 network outage) — plus the fact that Envoy already ran
as their service-mesh data plane made standardization the strategic goal.

The migration mechanics are the reusable part. They generated Envoy config
from Chef through a purpose-built library: a single per-host config object
assembled by resources, then validated (Envoy has a validate-only mode) before
install, so an invalid intermediate config can never land on disk. They stood
up a complete parallel Envoy stack mirroring the HAProxy tier and shifted
traffic by DNS weights — 10/25/50/75/100 percent per region, slow for early
regions, faster once confidence built — accepting doubled infrastructure cost
for the duration in exchange for instant rollback. They reverted, fixed, and
re-rolled several times for subtle mismatches (timeouts, headers), and still
briefly broke the DAU metric.

The retrospective lessons: years of organically grown LB config are mostly
undocumented behavioral contract — including accidents other services now
depend on (a service reachable under two vhosts by mistake had to stay that
way). Lacking automated routing tests, they had to interview service owners
to learn what behavior mattered; tests would have encoded that context. Their
config library deliberately exposed only the Envoy subset they used, which
kept it simple but meant every new feature required library work, and one
late-arriving need (vhosts) became an acknowledged hack. Comprehensive
generated-config snapshot tests made later library changes safe for every
consuming team.

## Key patterns & decisions

- Prefer dynamic endpoint discovery over config-reload cycles: a proxy that ingests endpoint changes live eliminates an entire class of reload/drain/reap tooling for long-lived connections.
- Hot restart with state carry-over: replacing binaries/config without dropping connections or resetting stats is a hard requirement when connections live for hours.
- Parallel-stack migration with weighted DNS: build an equivalent new tier next to the old one and shift traffic in small percentage steps per region, keeping instant rollback; accept temporary double cost as the price of a customer-invisible migration.
- Bug-for-bug compatibility during replacement: replicate even accidental behaviors of the old system (e.g., a service exposed under two vhosts) because consumers depend on them.
- Validate-before-install config generation: assemble the full config as a single object and gate installation on a validation pass so no intermediate/invalid config ever ships.
- Routing tests as executable documentation: absent automated tests asserting URL-to-backend routing and header behavior, migration requires interviewing service owners to rediscover intent.
- Subset-only abstraction layer: wrap only the proxy features you actually use — simpler library, but budget for incremental feature additions and occasional refactoring debt.
- Snapshot-test generated configs of all consumers: regenerate every team's full config in tests so library changes reveal their blast radius.
- Panic routing / graceful degradation: when the healthy-host fraction drops below a threshold, routing to all hosts beats routing to none during infrastructure-wide incidents.
- Standardize on one proxy across ingress and mesh to halve the operational surface (configs, quirks, build/release pipelines).

## When to apply / trade-offs

Use the parallel-stack + weighted-traffic playbook whenever replacing a
component in the live serving path, especially with long-lived connections
where draining is slow. The doubled infra spend is temporary and buys a
no-drama rollback story; Slack judged it clearly worth it. Expect the config
archaeology to dominate the schedule: separating intent from accretion in an
old config is slower than writing the new one. Write routing tests before the
migration, not after — they are cheap insurance and transferable
documentation. The subset-wrapper trade-off is genuinely two-sided: it kept
their Chef library maintainable but produced a known vhost hack when
requirements outgrew the abstraction. A "boring" migration — six months,
several reverts, zero customer impact — is the success criterion, not speed.

## Fidelity check

1. Claim: HAProxy reloads created process-management overhead. Capture
   describes new processes spawned per reload, old ones kept alive for many
   hours to drain websocket connections, and the need to periodically reap old
   processes and throttle reload frequency.
2. Claim: rollout used stepped DNS weighting with accelerating confidence.
   Capture states traffic moved via weighted DNS records in 10/25/50/75/100%
   steps, with early regions taking about a week and final regions compressed
   to two days at 25/50/75/100%.
3. Claim: they intentionally reproduced an old misconfiguration. Capture gives
   the example of services meant to live under one vhost but actually
   reachable under two in HAProxy, a mistake replicated in Envoy because
   existing code relied on it.
