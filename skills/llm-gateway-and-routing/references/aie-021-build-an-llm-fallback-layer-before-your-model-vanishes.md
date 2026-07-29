---
source: https://theroadtoenterprise.com/blog/model-agnostic-ai-layer-fallbacks
author: Thomas Findlay (The Road To Enterprise)
license-note: ideas absorbed in own words; no text or code reproduced
---

# A 429-only fallback chain misses the 404 from a withdrawn model

## What it adds beyond the primary

This is the first digest in the model-routing-fallback cluster, so it stands
alone rather than supplementing a primary. Its distinctive contribution is a
*failure taxonomy* for LLM calls rather than a gateway product comparison: the
author splits provider errors into exactly two buckets and makes failover
conditional on which bucket you are in. Availability errors — 404 (the model no
longer exists), 429 (throttled), and any 5xx — mean advance to the next model
in the chain. A 400 means "stop immediately", because a request the provider
judged malformed will be judged malformed by every other model too, so walking
the chain burns latency, tokens and money for a guaranteed failure. Any error
class you did not explicitly classify should also rethrow, on the grounds that
silently failing over on an unrecognised error hides bugs. The piece is anchored
to a concrete June 2026 incident and argues the structural lesson: the model ID
is runtime configuration, not a constant, and a hardcoded one is a single point
of failure. It is equally clear about what the pattern does *not* buy you.

## Primary source for this cluster

[aie-018-llm-routing-in-production-choosing-the-right-model-for-eve.md](aie-018-llm-routing-in-production-choosing-the-right-model-for-eve.md)

## Fidelity check

1. Claim: a fallback layer that only catches rate limits would have sailed past
   the failure that mattered, because a withdrawn model returns 404, not 429.
   Support: the capture states plainly that most fallback code people write only
   catches rate limits because that is the common case tutorials show, that the
   12 June shutdown was not a rate limit but a model returning 404 because it no
   longer existed, and that a 429-only layer would have missed the one error
   that mattered.
