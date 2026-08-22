---
source: https://dev.to/kuldeep_paul/adaptive-model-routing-and-fallback-logic-routing-around-llm-provider-outages-with-bifrost-4g3m
author: Kuldeep Paul (DEV Community; vendor post for Maxim AI's Bifrost gateway)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Failover belongs in the gateway, scored on live health, not a static list

## What it adds beyond the primary

Vendor post, so read the product claims sceptically — but it does contribute
two things the rest of the cluster does not spell out. First, a concrete
argument for *where* failover lives: doing it in application code means
duplicating per-provider SDKs, auth schemes, model identifiers and error
shapes; it makes retries purely reactive (they only fire after a request has
already failed, so traffic is never steered away from a degrading provider in
advance); and it silently drops middleware — caching, logging, governance,
rate limiting wired for the primary provider do not automatically apply on the
fallback path. Second, a worked scoring model: provider selection weighted on
error rate (50%), latency (20%, via what the post calls an MV-TACOS
algorithm) and utilisation (5%), with a momentum bias so a recovered provider
climbs back quickly; then a second, always-on level that picks the healthiest
API key inside the chosen provider, scored on error rate, latency, TPM hits
and a Healthy/Degraded/Failed/Recovering state, with roughly a quarter of
traffic deliberately explored onto recovering keys so they are not stranded
out of rotation. Weights are recomputed every five seconds, failed routes are
circuit-broken to zero weight, and a returning route gets a 90% penalty
reduction within thirty seconds. Two operational details are worth stealing
independent of the product: each fallback attempt is treated as a fresh
request so plugins re-run identically no matter who serves it, and the
response carries which provider actually answered, which is what makes
telemetry and cost attribution possible at all. A plugin can also veto the
retry — an auth failure should not be replayed down the whole chain with the
same broken credential. The precedence order (explicit routing rules, then
governance-pinned virtual keys, then performance-based provider choice only if
nothing pinned it, then key choice always) is a useful default for anyone
composing these layers. The overhead figure quoted (11 microseconds at 5,000
RPS) and the "20+ providers" reach are self-published vendor benchmarks and
should be treated as marketing until independently reproduced; adaptive load
balancing is also an enterprise-tier feature, not the open-source baseline.

## Primary source for this cluster

[aie-018-llm-routing-in-production-choosing-the-right-model-for-eve.md](aie-018-llm-routing-in-production-choosing-the-right-model-for-eve.md) — the primary digest for the model-routing-fallback cluster. Its
exact filename was not yet present on disk when this stub was written; the
sibling digest carrying the cluster's non-vendor treatment of routing and
failover is the one to read first.

## Fidelity check

1. Claim: provider scoring weights are error rate 50%, latency 20% (MV-TACOS),
   utilisation 5%, with a momentum bias aiding recovery, followed by weighted
   random selection with jitter and score-ordered fallbacks. Support: the
   capture reports these weights in its first-level provider-selection
   paragraph.
