# llm-gateway-and-routing

Engineering the boundary between an application and its LLM providers — tiered routing, fallback chains, health-aware failover, deprecation planning, and schema-constrained outputs.

## What this covers

This skill treats a model provider as an unreliable remote dependency rather than a library call, and encodes the patterns for surviving it:

- **Request classification and tiered routing** — triage on cost-versus-value, latency class, task difficulty, and compliance; five to ten rules in one decision table before anything cleverer; fast/smart/power tiers with price, latency, and traffic-share targets you can alert on
- **Confidence-based escalation** — cheap model first, escalate only the uncertain tail, with threshold calibration as the named failure mode
- **Failure taxonomy** — throttling, 5xx, retired-model 404, malformed request, safety refusal, timeout, schema-invalid response, and interrupted stream, each with an opposite correct response
- **Fallback chains** — same-provider hop before cross-vendor hop, policy filtering before health scoring, live health signals instead of a static ordered list, separate retry and fallback budgets
- **Why swapping the endpoint is not enough** — prompt portability per provider, re-validating fallback output against the same schema, running every attempt through the same middleware, returning which provider actually answered
- **Health checks, circuit breaking, and timeout budgets** at the provider boundary, with the mechanics deferred to the resilience rules
- **Streaming and tool-call safe points** — clean before the first token, restart-or-abort mid-stream, re-execution risk after a tool call
- **Model deprecation as a scheduled event** — model IDs as runtime configuration, calendar-driven migration, and why a 429-only fallback layer misses the 404 that matters
- **Cost and latency attribution per route** — logging the routing decision and reason, per-route slicing, and pricing the fallback path that fires at peak
- **Structured outputs as the substitution contract** — schema before prompt, enums on branching fields, reasoning before answer, provider schema divergence, refusals bypassing validation
- **Constrained decoding** — sample-time versus validation-time enforcement, why constraining can be faster, budgeting mask cost against the forward pass, and the shape-only limits of a token mask
- **Validation and repair** — capped repair loops with the repair rate as the real diagnostic, and distribution-based semantic validation that catches schema-valid nonsense

## Distinct from agent model tiering

`.claude/rules/model-tiers.md` decides which model tier an SDLC pipeline **agent** runs on for its own reasoning — a design-time choice recorded in agent frontmatter. This skill decides how an **application** dispatches **user traffic** across providers at runtime, per request, under failure. They share vocabulary and nothing else; keep the two decisions separate.

## Structure

- `SKILL.md` — Full pattern guide with YAML frontmatter, usage triggers, core conventions, anti-patterns, and references
- `references/aie-018-llm-routing-in-production-choosing-the-right-model-for-eve.md` — Routing as triage, the four routing dimensions, rule-based and confidence-based patterns, placement as a trust decision, when routing is premature
- `references/aie-019-llm-failover-and-load-balancing-for-provider-outages.md` — Failure taxonomy, header-driven backoff, two failover axes, policy filtering, quota pools versus keys, hedging cost, streaming failover
- `references/aie-020-adaptive-model-routing-and-fallback-logic-routing-around-p.md` — Reactive-versus-anticipatory failover, live health scoring with recovery momentum, each attempt as a fresh request, layer precedence order
- `references/aie-021-build-an-llm-fallback-layer-before-your-model-vanishes.md` — Availability errors versus request errors, 400 stops the chain, rethrow the unclassified, model ID as runtime configuration
- `references/aie-022-three-tier-llm-routing-fast-smart-and-power-model-stacks.md` — Tier price/latency/traffic-share targets, classifier latency against a routing-overhead budget, semantic caching, compliance-driven routing
- `references/aie-023-what-our-provider-fallback-actually-looks-like-after-month.md` — Field experience: burst versus monthly ceilings, separate retry and fallback budgets, failover safe points, the unpriced fallback, centralization trade-offs
- `references/aie-032-llm-structured-outputs-schema-validation-for-real-pipeline.md` — Schema before prompt, enums on branching fields, field ordering, provider divergence, capped repair loops, distribution-based semantic validation
- `references/aie-033-llguidance-super-fast-structured-outputs.md` — Sample-time enforcement, lazy versus precomputed automata and bimodal tails, mask cost against the forward pass, shape-only guarantees

Attribution: the digests are own-words summaries of the public articles named in each file's frontmatter; no source text or code is reproduced. Several sources are vendor publications, and their self-reported latency, throughput, and savings figures are treated as unverified.

## Usage

Reference this skill when:

- Designing or reviewing the call path between a service and one or more model providers
- Adding a second provider for redundancy, or reacting to a provider outage that caused a user-visible failure
- A depended-on model has a published retirement date, or a model ID is hardcoded in the service
- Inference spend is growing with traffic rather than with value
- Model output feeds another system and malformed or semantically empty responses are causing incidents
- Choosing between provider-native structured output, self-hosted constrained decoding, and validate-and-repair

## Cross-references

- **`.claude/rules/model-tiers.md`** — Agent-side model tier selection. Different problem; see the section above.
- **`.claude/rules/resilience-engineering.md`** — Timeouts, retry budgets and jitter, circuit-breaker mechanics, bulkheads, backpressure, load shedding, fallback sharp edges, fault injection. This skill applies those primitives to the provider boundary rather than restating them.
- **`.claude/rules/agent-resilience.md`** — The agent-side failure loop and 3-strike fix discipline.
- **langfuse-llm-tracing** — Emitting per-generation traces, token counts, and provider/model metadata. The routing layer's cost and quality attribution depends on this instrumentation.
- **observability-and-logging** — General service telemetry, structured logging, and alerting underneath the routing-specific fields.
- **otel-tracing** — Distributed tracing across classifier, primary, and fallback hops.
- **api-integration** — Typed client-side API integration, error handling, and loading states for the service that fronts this layer.
- **api-and-interface-design** — Versioning and compatibility discipline for the output schema treated as a published contract.
- **deprecation-and-migration** — Running the model-retirement cutover once the calendar alert fires.
- **redis-caching-patterns** — Concrete cache implementation behind the semantic-cache router stage.
- **security-and-hardening** — Credential handling, input validation, and injection defense on the values inside a validated schema.
