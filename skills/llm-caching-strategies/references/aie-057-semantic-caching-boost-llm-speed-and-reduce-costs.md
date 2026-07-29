---
source: https://www.truefoundry.com/blog/semantic-caching
author: Sahajmeet Kaur — TrueFoundry
license-note: ideas absorbed in own words; no text or code reproduced
---

# Put the semantic cache in the gateway, not the app, so hit rate compounds

## What it adds beyond the primary

Mostly corroborates the primary's core mechanic — embed the prompt, do a
nearest-neighbour lookup against previously cached prompt vectors, return the
stored answer when the best match clears a similarity threshold, otherwise call
the model and write the new response back. The one genuinely additional claim is
architectural placement: this piece argues the cache belongs in the LLM gateway
sitting in the request path ahead of model selection, not inside each
application. The stated payoff of that placement is a shared cache whose hit
rate rises as more services route through it, one central place to tune
similarity thresholds and TTLs, per-route and per-scope opt-in/opt-out (app,
team, environment, or shared), and cost/latency savings attributable back to the
calling app — none of which require touching application code. It also names two
demand profiles the primary underweights: agentic multi-step systems, where an
agent rephrases the same sub-question across runs, and on-prem or
GPU-constrained deployments, where the cache is a way to stretch fixed inference
capacity rather than to shave an API bill.

## Primary source for this cluster

[aie-054-prompt-caching-vs-semantic-caching-how-to-make-ai-agents-f.md](aie-054-prompt-caching-vs-semantic-caching-how-to-make-ai-agents-f.md)

## Fidelity check

1. Claim: gateway placement gives a shared cache, central threshold/TTL control,
   scope and opt-in/opt-out controls, and per-app attribution without app code
   changes. Support: the capture devotes a section to TrueFoundry's own
   implementation, enumerating a shared cache across teams, centralized
   similarity thresholds and TTL policies, scope controls per app/team/env,
   per-route opt-in/opt-out, and token/inference savings attribution by app or
   team.
