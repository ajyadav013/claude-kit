---
name: llm-gateway-and-routing
description: Route application LLM traffic across providers — request tiering, fallback chains, health-aware failover, deprecation planning, and schema-constrained outputs. Use when a production service calls model providers on a path that must succeed.
---

# LLM Gateway and Routing

A model provider is a remote dependency that meters you, throttles you, retires its own product on a published date, and occasionally goes down mid-sentence. Applications that call one provider directly inherit every one of those properties. This skill covers the layer that sits between your service and every provider it uses — how a request is classified and sent to an appropriately-sized model, what happens when that model is unavailable, and why a schema-constrained response is the thing that makes swapping the model underneath safe.

## When to use

- Designing the call path between an application and one or more LLM providers, where model failure is a user-visible failure
- Inference spend is growing with traffic rather than with value, and one strong model is being applied uniformly to every request
- A provider incident, regional degradation, or rate-limit storm took a product feature down and the team wants that to be survivable next time
- A model you depend on has a published retirement date, or a model ID is hardcoded somewhere in the service
- Adding a second provider for redundancy and needing to know what else changes besides the endpoint
- Latency is erratic — interactive requests are queued behind work that could have run on a cheaper, faster model
- Model output crosses a system boundary (analytics columns, routing decisions, tool arguments, stored records) and malformed or semantically empty responses are causing downstream incidents
- Choosing between provider-native structured output, self-hosted constrained decoding, and a validate-and-repair loop
- More than one service in the organization calls models, and per-service retry logic is starting to diverge
- Attributing cost and latency to a specific route, model, or tier — including the cost of the fallback path itself

Scope boundary — this skill owns **the application-to-provider boundary**. Adjacent territory is owned elsewhere:

- **`.claude/rules/model-tiers.md` is a different problem.** That rule governs which model tier an *agent in this SDLC pipeline* runs on for its own reasoning — a design-time frontmatter decision made once per agent. This skill governs how an *application* dispatches *user traffic* across providers at runtime, per request, under failure. The two share the vocabulary of tiering and the discipline of "escalate deliberately, not reflexively"; they share nothing else. Do not apply agent-tier policy to production traffic routing, and do not let a runtime router decide which model a pipeline agent uses.
- Retry/backoff/jitter mechanics, circuit-breaker state machines, bulkheads, backpressure, load shedding, deadline propagation, and the sharp edges of fallbacks are owned by `.claude/rules/resilience-engineering.md` (always loaded). Sections below apply those primitives to the provider boundary rather than restating them.
- The agent-side fix-attempt loop and 3-strike discipline live in `.claude/rules/agent-resilience.md`.
- Emitting the traces, token counts, and per-generation metadata this skill's attribution depends on is owned by `langfuse-llm-tracing`; general service telemetry is owned by `observability-and-logging`.

## Core conventions

### Treat the provider boundary as a dependency with its own layer

1. **Name the layer before designing it.** Whether it is a module in one service, a shared internal library, or a separate proxy process, one component should own model selection, credential handling, retry policy, failover, and output validation. The alternative is not "no layer" — it is the same layer implemented five slightly different ways in five services, each with its own subtly wrong retry policy, discovered during an incident.

2. **Centralization has a real cost — price it honestly.** Collapsing N provider integrations behind one router trades many small failure points for one new shared one, and it can forfeit provider-native features that only work on the direct path — prompt caching keyed to a provider's own cache, batch-tier discounts, provider-specific streaming semantics. Practitioners report both losses as surprises found on an invoice. If the router is a separate process, it is now on the critical path of every request and needs its own availability target, its own deploy safety, and a documented behavior for "the router itself is down."

3. **Never recommend or assume a specific commercial gateway.** Several products implement these patterns well, and every published latency and savings figure from a vendor is marketing until independently reproduced on your workload. The patterns in this skill are implementable in a few hundred lines against an existing backend. Buy if the operational burden outweighs that; never buy because a benchmark table said so.

### Classify the request before choosing a model

4. **Routing is triage, and the dispatcher is the easy part.** The engineering difficulty is not the mechanism — most production routing is plain conditional logic — but understanding your own workload well enough to put requests into meaningful categories. A router built before the workload is understood just adds a hop.

5. **Route on four dimensions, hardest last.** Cost against the business value of the request; latency class (interactive versus background); task difficulty against required capability; and privacy or regulatory constraints. The first two are usually derivable from request metadata. Difficulty is the genuinely hard one. Compliance is not a dimension to trade against the others — it is a hard filter that runs first and can disqualify an otherwise-optimal choice.

6. **Route on request context, not task name.** Summarizing a document while a user waits and summarizing the same document in an overnight backfill are the same task with opposite latency requirements. Any classification keyed to the operation name alone will get one of the two wrong.

7. **Start with five to ten rules in one place.** Input size, caller tier, endpoint, and time of day capture most of the meaningful variation in a typical workload — reportedly around 80% of routing need. Keep them in a decision table or config, not as conditionals scattered across handlers. The decisive advantage of rules over anything cleverer is traceability — a log line naming the matched rule and the chosen model makes every decision explainable to someone who was not there.

8. **Budget the classifier's own latency against the routing overhead.** Published figures for the three common techniques differ by two orders of magnitude — rule evaluation in the tens of milliseconds, embedding or semantic similarity in the low hundreds, and an LLM-based classifier in the hundreds to low thousands — against a total routing overhead budget on the order of 200ms for interactive paths. That arithmetic rules out an LLM classifier for interactive traffic before any accuracy discussion happens. Classification accuracy does not need to be perfect either; an imperfect classifier that is right most of the time still pays for itself at volume, so do not let it block a useful rule-based first version.

### Give the tiers numeric targets

9. **Three tiers is the working shape.** A fast tier for high-volume mechanical work, a mid tier for the general case, and a top tier for genuinely hard reasoning. What makes the tiering operable is attaching numbers to each — a price band per unit of tokens, an expected response-time band, and a **target share of traffic**. Commonly cited targets put roughly half of traffic on the fast tier, a third on the mid tier, and only ten to twenty percent on the top tier.

10. **The traffic share is the metric you actually alert on.** Price bands drift and latency bands vary by provider, but the distribution is yours to control. When top-tier share climbs past its target, the router has stopped triaging, and the invoice will say so a month later. Overuse of the most capable tier is the single largest source of avoidable inference spend.

11. **Escalate on measured uncertainty, not on hope.** The confidence-based pattern sends everything to the cheap model first, serves the confident answers directly, and escalates only the uncertain tail to a capable model. It fits classification, extraction, and routing tasks where a usable confidence signal exists. The economics are simple — if the cheap model resolves 70% of requests confidently, you have removed 70% of expensive calls and pay only one extra cheap hop on the remainder. The failure mode is entirely in threshold calibration — too strict and you pay for both models on most requests, too loose and you ship low-quality answers with a cost saving to show for it.

12. **Cache before you route, if the workload repeats.** A semantic cache in front of the router — embed the request, search prior entries by similarity, serve on a hit — removes the request from the routing problem entirely. Start the similarity threshold conservatively (0.95 is a commonly cited starting point) and tune per use case, because a too-loose threshold serves a confidently wrong cached answer. Plan invalidation up front — time-based, event-based on source-data change, and size-based eviction.

13. **Compliance routing overrides everything above it.** Tag requests by data sensitivity, keep regulated data inside approved regions and approved providers even when that means a weaker model or a worse price, detect or mask personal data before dispatch, and audit-log the routing decision itself so the constraint can be proven after the fact. A route restricted by residency must not silently fail over to a global endpoint just because it is the healthy one.

### Classify the failure before reacting to it

14. **"Error, retry" is the default that causes the outage.** Distinct failure classes need opposite responses, and collapsing them into one retry policy makes every class worse. The taxonomy worth encoding:

    | Class | Signal | Correct response |
    |-------|--------|------------------|
    | Throttling | 429, `Retry-After` or remaining/reset headers | Honor the server's timing signal with jitter; shift to a different quota pool |
    | Server fault | 5xx | One or two quick retries, then advance the chain |
    | Model gone | 404 on a model ID | Advance the chain immediately and page someone — this is a deprecation, not a blip |
    | Malformed request | 400 | Stop. Every other provider will reject it too |
    | Content refusal | Safety block | Never retry; route to a remediation path |
    | Timeout / silent slowness | Response within SLO not arriving | Fail over quickly; the request is not coming back cheaper |
    | Schema-invalid response | Validator failure | Bounded repair loop, then fail over or fail safe |
    | Interrupted stream | Connection drop mid-generation | Decide by safe point (see below) |
    | Unclassified | Anything else | Rethrow. Silent failover on an unrecognized error hides bugs |

15. **A quota dashboard showing headroom does not mean you are not throttled.** Per-minute burst ceilings and monthly quota ceilings are separate limits — practitioners report being rate-limited during a traffic spike while the monthly dashboard still showed capacity remaining. The `Retry-After` header is the signal that you are being throttled rather than exhausted. Retrying harder against the same endpoint extends the throttle instead of ending it.

16. **A safety refusal is a property of the request, not a transient fault.** The same input produces the same refusal, and another provider will usually refuse it too. Retrying spends latency and tokens for a guaranteed failure. Send it to a policy-remediation path — rewrite the prompt, ask the user for a different input, route to a safer flow — and count refusals as their own metric.

17. **Keep the retry budget and the fallback budget separate.** A retry is another attempt at the same provider; a fallback is a different provider or model. Two or three retries is a reasonable ceiling — beyond that you are only delaying the fallback that would have succeeded, while adding load to a dependency that is already struggling. Track them as separate counters so "we retried a lot" and "we failed over a lot" are distinguishable in a postmortem.

18. **More API keys under one account is not more headroom.** Providers commonly enforce limits at the organization, project, or model-family level, so additional keys under the same organization draw from the same pool. Genuine capacity comes from separate providers, separate regions, separate projects, or separate accounts — and the balancer should route against remaining capacity as reported in rate-limit headers, not against a static weight.

### Order the fallback chain by independence, filter it by policy

19. **Two failover axes with different blast radii.** An alternate region, deployment, or model family inside the same provider is cheap to add and keeps prompts and output shapes identical — but it shares a failure domain with the thing that just failed. Crossing to a different vendor buys genuinely independent infrastructure and costs you portability work. A sound chain tries the cheap same-provider hop first, then crosses vendors.

20. **Filter candidates by policy before any cost or health scoring runs.** Data residency, customer allowlists, regulated-data rules, contractual terms, and whether the candidate supports the tools and schemas the request needs can each disqualify a provider. Health scoring over an unfiltered candidate set will eventually route regulated traffic to a healthy but forbidden endpoint.

21. **Prefer live health scoring over a static ordered list.** A static list is purely reactive — traffic only moves after a request has already failed, so a degrading provider keeps absorbing requests until each one times out. Scoring candidates continuously on recent error rate, recent latency, and current utilization lets traffic drift away from a provider *before* it fully fails. Two implementation details are worth adopting regardless of how the scoring is done — recompute on a short interval rather than per request, and deliberately route a small exploratory share of traffic to a recovering candidate so it is not stranded out of rotation by the same score that demoted it.

22. **Circuit-break the dead candidate to zero weight and let it climb back fast.** The breaker state machine itself belongs to `.claude/rules/resilience-engineering.md`; what is specific here is that provider recovery is usually abrupt rather than gradual, so a recovery path that heavily penalizes a returning provider for minutes leaves capacity unused during exactly the period you need it. A short probe window and a fast penalty decay is the right shape.

23. **Set per-hop timeouts from the healthy provider's own distribution, and bound the total.** A per-attempt deadline near the healthy backend's p95 to p99 is a reasonable starting point, tuned to your SLO rather than adopted as a constant. Crucially, the *sum* of attempts across the chain must still fit inside the caller's deadline budget — a three-provider chain with generous per-hop timeouts produces a request that succeeds long after the user gave up. Propagate the deadline and check it before each hop.

24. **Hedging is a tail-latency tool with a cost multiplier, not a default.** Firing a duplicate request once the primary passes roughly its p95 does cut p99, but you pay for two calls, a cancelled call may still bill for tokens already generated, and for anything that invokes tools the duplicate can execute a real side effect twice. Enable it per route, never globally.

25. **Let the caller veto a retry.** Some failures should stop the chain regardless of class — an authentication failure replayed down every provider with the same broken credential just multiplies the error. A hook that can mark an attempt non-retryable is cheap to add and prevents a whole family of amplification bugs.

### A different provider is a different program

26. **Failover buys availability by spending fidelity.** The fallback model formats differently, refuses different inputs, follows instructions differently, and reasons differently. The answer the user gets during a failover is not the answer the primary would have produced. This is usually the right trade — but it must be a stated, observable degradation, not an invisible one.

27. **Keep prompts portable, and version them per provider when they cannot be.** A prompt tuned against one model's quirks is a hidden coupling. Where a provider genuinely needs its own phrasing, system-message placement, or tool-definition shape, store it as an explicit per-provider variant tied to the same logical prompt version — not as a fork nobody remembers to update.

28. **Re-validate the fallback's output against the same contract.** This is the single most-skipped step in provider failover. Swapping the endpoint is trivial; guaranteeing the response still satisfies the schema, the enum values, and the semantic checks downstream code relies on is the actual work. Every candidate in the chain must pass the same validation the primary passes, and a candidate that cannot express the schema is not a candidate.

29. **Make every attempt a full request, not a patch on the previous one.** Middleware wired for the primary — caching, logging, rate limiting, governance, redaction, tracing — must run identically on the fallback path. When failover is implemented as an inline exception handler around one provider call, that middleware silently does not apply, and the fallback path becomes the unobserved, ungoverned one. Running each attempt through the same pipeline is what prevents that.

30. **Return which provider actually answered.** The response must carry the provider, model ID, attempt number, and whether it came from a cache. Without that field, cost attribution, quality comparison, and incident reconstruction are all guesswork.

### Streaming and tool calls have safe points

31. **Failover safety is a function of what has already been committed.** Before the first token reaches the user, switching is clean. Once tokens are on screen, there is no honest way to splice a second provider into one transcript — the choices are to restart the response visibly or to abort with an error. After a tool call has executed a real side effect, failing over usually means re-executing work, so idempotency of the tools decides whether that is even legal.

32. **Choose the streaming strategy per path, not globally.** Buffering server-side before emitting gives clean failover at the cost of the perceived-latency benefit that motivated streaming. Accepting a visible restart keeps the latency benefit and shows the user a hiccup. Confirming liveness with a non-streamed first call before committing to a stream is the middle option. A customer-facing chat and a batch agent should not make the same choice.

### Model deprecation is a scheduled event

33. **The model ID is runtime configuration, not a constant.** A hardcoded model string is a single point of failure with a known expiry date. It belongs in config that can be changed without a deploy, and the set of currently-approved models belongs in one place the whole service reads.

34. **A 429-only fallback layer misses the failure that actually matters.** Most fallback code catches rate limits, because that is the case tutorials show. A withdrawn model does not return 429 — it returns 404, and a chain that only advances on throttling walks straight into a hard failure on the day the retirement lands. Practitioners have been caught by exactly this.

35. **Run deprecation as a planned migration.** Track every provider's announced retirement dates against the models your config actually references; alert when a referenced model has a date inside your planning horizon. Before the date, run the replacement model against a held-out set of real requests and compare outputs on the dimensions you care about, not just on whether they parse. Migration mechanics — parallel run, staged cutover, rollback criteria — are owned by `deprecation-and-migration`; what this skill adds is that the trigger is a calendar entry, and the cost of missing it is a 404 in production.

### Attribute cost and latency per route

36. **Log the decision, not just the outcome.** Every request should record the chosen model and provider, the reason (matched rule, confidence threshold, fallback position, cache hit), the attempt count, and a correlation ID that survives across hops. Distributed tracing is what makes a path spanning classifier, primary, and two fallbacks debuggable at all — `langfuse-llm-tracing` covers emitting the generation-level spans and token counts, and `otel-tracing` the transport.

37. **Slice cost, latency percentiles, error rate, and retry frequency per route.** Aggregate numbers hide the whole point of routing. The questions a router must be able to answer are which routes are saving money, which are silently escalating, and which tier's share is drifting from target.

38. **Price the fallback path explicitly, because it fires at exactly the wrong moment.** Failover triggers during peak load — which means your most expensive traffic hour is the one where requests are being served by the backup, often a pricier model, frequently after paying for a failed primary attempt as well. An unpriced fallback is a bill you discover at the end of the month. Model the cost of the chain, not just the cost of the happy path, and alert on fallback rate as a spend signal rather than only as a reliability signal.

39. **Watch for cost-cutting that shows up as quality loss.** Routing too much traffic down to a cheaper tier produces savings on the inference line and costs elsewhere — retries, escalations, support contacts, abandoned sessions. Pair every cost metric with a quality metric on the same route, or the optimization will look successful right up until churn shows up.

### Structured output is the substitution contract

40. **A schema is what makes provider substitution safe.** Everything above assumes the fallback's response is usable by the same downstream code. That assumption only holds if the response shape is a contract enforced at the boundary rather than a habit the primary model happened to have. Design the schema before the prompt and treat it as an API contract — the prompt fills the contract; it does not define it. The same contract applies to tool-call arguments and tool results, where recent tool-server specifications have made declared output schemas mandatory rather than optional — a tool result is model-adjacent data crossing a boundary, so it gets the same treatment as a completion.

41. **Every field must earn its place.** If a field does not drive a branch, support a join, or get stored, remove it. Flat schemas with a few tightly-constrained fields validate more reliably and compile into decoding constraints more cheaply than rich schemas full of loose strings.

42. **Enums for anything that branches; bounds on everything numeric.** A freeform string on a field that selects a code path is an invitation to invented values. Push constraints into the contract — enumerated values, regex-bounded identifiers, numeric ranges, string length caps, array size limits — rather than into downstream cleanup code.

43. **Field order is logic, not formatting.** Required properties are generated in order, so a schema that places the answer field before the reasoning field forces the model to commit before it has reasoned. The JSON is valid, validation passes, and the answer is worse. Put reasoning, evidence, and citations ahead of conclusions.

44. **Provider portability of schemas is not free — verify it per candidate.** Vendors differ in parameter shape, in which JSON Schema keywords they honor, and in their published limits on tool count and optional or union-typed parameters. At least one provider silently ignores unsupported keywords, producing wrong-shaped output with no error to catch. Any schema you intend to run across a fallback chain must be tested against every candidate in that chain, not just the primary.

45. **Refusals bypass the schema entirely.** A safety-blocked request returns a refusal object, not schema-compliant data. A naive validate-and-retry loop will spin on it until the retry cap. Detect refusal as a distinct terminal outcome before the validator runs.

### Choose where the schema is enforced

46. **Two enforcement points, with different costs.** After generation — parse, validate, and retry on failure — or during sampling, by computing at every decoding step the set of tokens that can still lead to a valid string and masking the rest of the logits. Sample-time enforcement makes syntactically invalid output impossible by construction and removes the syntactic retry loop entirely. Provider-native structured output is the managed form of this; self-hosted constrained decoding engines are the form you run yourself.

47. **Constraining can be faster than not constraining.** Grammar enforcement prunes the search space, so fewer tokens are spent on dead ends, and where a grammar admits exactly one continuation those tokens can be emitted without invoking the model at all. Reported speedups reach an order of magnitude on rigid schemas. The intuition that "constraints cost latency" is backwards for this class of work.

48. **If you self-host, budget the mask against the forward pass and look at the tail, not the mean.** A constrained decoder that costs more than a forward pass converts a correctness feature into a throughput regression. Published figures for a well-optimized engine put average mask computation in the tens of microseconds per token on a large vocabulary with negligible startup cost, with a bounded tail. Designs that precompute masks can be bimodal — very fast when the precomputation fits the schema, orders of magnitude slower when it does not, which is a poor trade for a shared serving tier. When comparing engines, the questions are tail latency and startup cost measured on *your* schemas, not headline throughput.

49. **Over-constraining has its own failure mode.** Very large enums, dense cross-field constraints, and deeply recursive schemas can push a constrained-decoding engine into compile timeouts or unsupported-construct rejections, and grammar compilation caches are invalidated by any schema edit. Constrain what downstream code actually depends on and no more.

50. **Constrained decoding guarantees shape, and nothing else.** A perfectly-formed object with hallucinated field values passes every token mask. It is not a substitute for validating and authorizing the parsed result, and it does nothing about prompt injection reaching the values inside the fields.

### Validate, repair, and measure

51. **Bound the repair loop and instrument it.** On a validation failure, feed the validator's actual error text back and regenerate — capped at one or two attempts, then fail safely down the chain. The retry rate per prompt is the diagnostic that matters — a prompt that routinely needs two repairs is a broken prompt or a broken schema, and adding retries hides it rather than fixing it.

52. **Semantic validation checks distributions, not types.** Schema validation cannot detect a classifier that returns a valid enum with a confidence of 0.99 on every input including nonsense — a real reported failure that ran for two weeks. Monitor per-field distributions and alert when one stops moving. Requiring verbatim evidence spans that can be checked against the source input makes fabrication measurably harder and gives the validator something concrete to test.

53. **Version the schema in lockstep with the prompt, and treat changes as breaking.** Downstream consumers depend on the shape. A schema change is an API change, with the same compatibility discipline — `api-and-interface-design` owns that discipline.

54. **Persist the validated output as a replayable event.** Store the record alongside the input hash, prompt version, schema version, provider and model ID, route reason, retry count, latency, and token counts. That turns "which fields fail most", "which routes degraded", and "did the fallback model's label distribution shift" into queries instead of guesswork — and it is the same record the cost-attribution section needs.

### Place the routing layer where the trust is

55. **Placement is a trust decision before it is a latency decision.** Client-side routing avoids a hop, but clients are untrusted, so pricing tiers, spend caps, and compliance rules cannot be enforced there. Server-side routing costs an extra hop — commonly cited at roughly 100 to 300 milliseconds for globally distributed users — and buys enforcement, observability, and credential safety. The usual production shape is hybrid — the edge makes simple latency-critical choices, the backend makes every trust-bearing one, and the server can always override what the client asked for.

56. **Provider credentials live only on the trusted side.** This is not negotiable regardless of the routing topology; `security-and-hardening` owns the general handling of that secret material.

57. **Establish a precedence order and document it.** When several layers can influence the choice, ambiguity produces surprising routes. A workable default — an explicit per-request routing directive wins, then a policy or governance pin, then health-and-cost-based selection among whatever remains, with credential or pool selection inside the chosen provider applied last, always.

58. **Routing logic is code and needs tests.** Assert that each rule matches what it claims, that the chain advances correctly per failure class, that a policy-restricted request cannot reach a disallowed provider, that the deadline budget is respected across a full chain, and that routing metadata propagates all the way to the response. Simulate provider failures rather than waiting for real ones — fault injection discipline is owned by `.claude/rules/resilience-engineering.md`.

### Walk the request path end to end

59. **Every stage below maps to one convention above; a design review that cannot narrate this path has found its gap.**

    ```
    request → policy filter (residency, allowlist, capability)   [conv. 13, 20]
            → semantic cache lookup → hit? return                [conv. 12]
            → classify (rules first, budgeted latency)           [conv. 7, 8]
            → select tier + candidate, health-scored             [conv. 9, 21]
            → attempt 1 (deadline from remaining budget)         [conv. 23]
                 → validate schema → semantic checks             [conv. 46, 51, 52]
                 → ok? record provider + reason + cost → return  [conv. 30, 36, 54]
            → failure → classify it                              [conv. 14]
                 → non-retryable (400, refusal, unclassified)? stop / remediate
                 → throttle? honor Retry-After, shift quota pool [conv. 15, 18]
                 → advance chain: next candidate, full request   [conv. 19, 29]
                      → re-validate against the same schema      [conv. 28]
            → chain exhausted → fail safely, degrade observably  [conv. 26]
    ```

60. **The degradation story is part of the design, not the postmortem.** Name in advance what the caller receives when the chain is exhausted — a cached or stale answer, a reduced-functionality response, or an honest error — and make that outcome emit its own signal. A silently successful fallback and a silently degraded answer both look like health on a dashboard, which is how a provider outage runs for hours before anyone notices.

### Know when not to build this

61. **Routing is premature below a real pain threshold.** At modest volume and modest spend, with an early-stage product still finding its shape, or where every request has genuinely the same difficulty profile, a router costs more engineering time than it saves and adds a latency hop, a new class of failure modes, threshold-calibration work, and a test surface most teams forget. Build it when you can name the pain — spend outgrowing value, latency variance hurting conversion, genuinely divergent use cases sharing one model, or an outage that took you down.

62. **Fallback machinery is still worth it earlier than routing is.** The asymmetry matters — sophisticated tiered routing is an optimization, but a deprecation-aware fallback chain is insurance against a dated, announced, certain event. Even a service that legitimately needs only one model should not hardcode which one.

63. **Some workloads should not fail over at all.** When contract or regulation pins a workload to one vendor, cross-provider failover is not available and pretending otherwise produces a compliance incident during an outage. The honest design there is within-provider redundancy plus a written, tested degradation story.

## Anti-patterns to avoid

- **One strong model for every request** — spend scales with users instead of value, and interactive requests queue behind work a fast model could have finished. Tier the traffic and give each tier a target share.
- **Treating every provider error the same** — a 400, a safety refusal, and a 404 on a retired model each get worse when handled as "retry the same call." Classify first, then react.
- **A fallback chain that only catches 429** — the failure that eventually matters is a withdrawn model returning 404, which a throttling-only chain walks straight past.
- **Hardcoded model IDs** — a constant with a published expiry date. Model selection is runtime configuration.
- **Retrying a content refusal** — the same input produces the same refusal, at every provider. It belongs on a remediation path, not in the chain.
- **Retrying harder against a throttled endpoint** — ignoring `Retry-After` and hammering the same quota pool extends the throttle. Honor the server's signal and shift pools.
- **Adding API keys to buy rate-limit headroom** — keys under one organization usually share one pool. Real headroom comes from separate providers, regions, projects, or accounts.
- **Failing over the endpoint without re-validating the output** — the fallback model formats, refuses, and reasons differently. Every candidate must satisfy the same schema and semantic checks as the primary.
- **Failover implemented as an inline exception handler** — caching, logging, governance, redaction, and tracing wired for the primary silently do not run on the fallback path, leaving the degraded path the unobserved one.
- **A chain whose total timeout exceeds the caller's deadline** — every hop succeeds and the user has already left. Propagate the deadline and check it before each attempt.
- **Splicing a second provider into a stream already in progress** — there is no clean mid-stream handoff. Restart visibly, abort, or buffer before the first token; decide per path.
- **Failing over after a tool call has executed** — the side effect already happened. Either the tools are idempotent or the safe point is before the call.
- **An unpriced fallback path** — failover fires at peak, routing your most expensive hour to the more expensive backup, and you find out from the invoice. Alert on fallback rate as a spend signal too.
- **Aggregate-only cost and latency metrics** — without per-route slicing there is no way to tell which routes help, which are silently escalating, or which tier has drifted off target.
- **Cutting cost until quality drops** — the savings appear on the inference line while retries, escalations, and churn appear elsewhere. Pair every cost metric with a quality metric on the same route.
- **An LLM classifier on an interactive routing path** — hundreds to thousands of milliseconds spent deciding, against a routing budget measured in low hundreds. Use rules, or classify offline.
- **A static ordered fallback list treated as health awareness** — purely reactive, so traffic keeps flowing into a degrading provider until each request times out. Score candidates on live signals.
- **Health scoring over an unfiltered candidate set** — residency, contractual, and capability constraints must eliminate candidates before cost or health logic runs, or a healthy-but-forbidden endpoint eventually wins.
- **Trusting schema validity as correctness** — a constant confidence score, a frozen label distribution, or a fabricated citation all pass the validator. Monitor distributions and demand checkable evidence.
- **Answer fields before reasoning fields** — required properties emit in order, so the model commits before it reasons; the output is valid and worse.
- **An uncapped validate-and-repair loop** — it spins forever on a refusal and hides broken prompts behind retry count. Cap it, then fail safely, and alert on the repair rate.
- **Over-constraining the schema** — huge enums and dense cross-field constraints push decoding engines into compile timeouts and unsupported-construct rejections. Constrain only what downstream code relies on.
- **Enforcing pricing, budgets, or compliance in client-side routing** — clients are untrusted; those decisions belong on the server, which must be able to override what the client requested.
- **Building the router before the workload is understood** — the mechanism is the easy part; a router over categories nobody has validated is a latency hop with a config file.
- **Applying agent-tier policy to production traffic** — `.claude/rules/model-tiers.md` governs which model a pipeline agent reasons on, not how user requests are dispatched. Keep the two decisions separate.

## References

Digests (own-words summaries of the sources, in `references/`):

- [aie-018-llm-routing-in-production-choosing-the-right-model-for-eve.md](references/aie-018-llm-routing-in-production-choosing-the-right-model-for-eve.md) — routing as triage, the four routing dimensions, rule-based and confidence-based patterns, placement as a trust decision, routing observability fields, when routing is premature
- [aie-019-llm-failover-and-load-balancing-for-provider-outages.md](references/aie-019-llm-failover-and-load-balancing-for-provider-outages.md) — failure taxonomy, header-driven backoff, two failover axes, policy filtering before health logic, quota pools versus keys, hedging cost, streaming failover per path
- [aie-020-adaptive-model-routing-and-fallback-logic-routing-around-p.md](references/aie-020-adaptive-model-routing-and-fallback-logic-routing-around-p.md) — why failover in application code is reactive and drops middleware, live health scoring with recovery momentum, each attempt as a fresh request, responses carrying the answering provider, layer precedence order
- [aie-021-build-an-llm-fallback-layer-before-your-model-vanishes.md](references/aie-021-build-an-llm-fallback-layer-before-your-model-vanishes.md) — availability errors versus request errors, 400 stops the chain, rethrow the unclassified, the model ID as runtime configuration
- [aie-022-three-tier-llm-routing-fast-smart-and-power-model-stacks.md](references/aie-022-three-tier-llm-routing-fast-smart-and-power-model-stacks.md) — fast/smart/power tiers with price, latency and traffic-share targets, classifier latency priced against a routing-overhead budget, semantic caching as a router stage, compliance-driven routing
- [aie-023-what-our-provider-fallback-actually-looks-like-after-month.md](references/aie-023-what-our-provider-fallback-actually-looks-like-after-month.md) — field experience: burst versus monthly ceilings, separate retry and fallback budgets, failover safe points, the unpriced fallback firing at peak, centralization forfeiting provider-native caching and batch discounts
- [aie-032-llm-structured-outputs-schema-validation-for-real-pipeline.md](references/aie-032-llm-structured-outputs-schema-validation-for-real-pipeline.md) — schema before prompt, enums on branching fields, reasoning-before-answer ordering, provider schema divergence, refusals bypassing the schema, capped repair loops, distribution-based semantic validation, replayable output events
- [aie-033-llguidance-super-fast-structured-outputs.md](references/aie-033-llguidance-super-fast-structured-outputs.md) — sample-time versus validation-time enforcement, lazy versus precomputed automata and bimodal tails, budgeting mask cost against the forward pass, fast-forward tokens, shape-only guarantees

Attribution: each digest summarizes the public article named in its frontmatter — own-words summaries, no verbatim text. Several sources are vendor publications; their published latency, throughput, and savings figures are self-reported and treated here as unverified.

Related skills and rules:

- `.claude/rules/model-tiers.md` (always loaded) — which model tier an SDLC *agent* runs on. Design-time, per agent, for the agent's own reasoning. Explicitly not this skill's problem.
- `.claude/rules/resilience-engineering.md` (always loaded) — owns timeouts, retry budgets and jitter, circuit-breaker mechanics, bulkheads, backpressure, load shedding, fallback sharp edges, and fault injection
- `.claude/rules/agent-resilience.md` (always loaded) — the agent-side failure loop and 3-strike fix discipline
- `langfuse-llm-tracing` — emitting per-generation traces, token counts, and provider/model metadata that this skill's cost and quality attribution depends on
- `observability-and-logging` — general service telemetry, structured logging, and alerting underneath the routing-specific fields
- `otel-tracing` — distributed tracing across classifier, primary, and fallback hops
- `api-integration` — client-side API integration with typed contracts, error handling, and loading states for the service that fronts this layer
- `api-and-interface-design` — versioning and compatibility discipline for the output schema as a published contract
- `deprecation-and-migration` — running the model-retirement cutover once the calendar alert fires
- `redis-caching-patterns` — concrete cache implementation behind the semantic-cache stage
- `security-and-hardening` — credential handling, input validation, and injection defense on the values inside a validated schema
