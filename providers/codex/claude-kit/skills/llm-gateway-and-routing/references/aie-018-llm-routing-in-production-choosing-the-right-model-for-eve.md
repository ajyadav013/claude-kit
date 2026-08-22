---
source: https://blog.logrocket.com/llm-routing-right-model-for-requests/
author: Alexander Godwin (LogRocket Blog)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Per-request LLM routing is triage: five to ten if-then rules, not ML

## What it teaches

Teams typically ship an LLM product on one strong model applied uniformly to
every use case, then discover that spend scales with users instead of value,
that latency is erratic, and that one provider incident takes the whole
product down. Routing is the response: decision logic that inspects a
request's characteristics and sends it to an appropriate model. The article's
central correction is that the hard part is not the routing mechanism — most
production routing is plain conditional logic — but understanding your own
workload well enough to categorise it. It gives four routing dimensions (cost
versus request value, interactive versus background latency, task complexity
versus model capability, and privacy/compliance constraints), three concrete
patterns (rule-based, confidence-based escalation, fallback chains with
circuit breakers), guidance on where routing logic should physically live
(client, backend, hybrid), a routing-specific observability contract, and an
explicit list of situations where routing is not worth the complexity. It
closes with a comparison of build-your-own against six gateway/router
products, each with a stated latency or pricing cost.

## Key patterns & decisions

- **Routing is triage, and the mechanism is the easy part** — The article's
  framing is an emergency-room triage desk: nobody sends every patient to the
  most specialised surgeon. The sophistication lives in categorising work
  meaningfully, not in the dispatcher. Reinforcement-learning routers exist
  but are not where a team starts.

- **Route on four dimensions, in this order of hardness** — Cost versus
  business value per request; latency class (interactive versus background);
  task complexity versus required capability; and privacy/compliance. The
  first two are usually knowable from metadata; complexity is the genuinely
  hard one; compliance is a hard boundary that overrides the other three.

- **The same task changes class with context** — Summarising a document a
  user just uploaded while they wait is interactive; summarising yesterday's
  uploads in an overnight job is a background request. Identical work, opposite
  routing. So route on the *request context*, not on the task name.

- **Rule-based routing handles roughly 80% with five to ten rules** — Input
  length, user tier, request endpoint, and time of day capture most of the
  meaningful variation. Its real advantage is traceability: a log line naming
  the matched rule and the chosen model makes every decision explainable.
  Keep the rules centralised in config or a decision table, not scattered as
  hard-coded conditionals across the codebase.

- **Confidence-based routing = try cheap, escalate when uncertain** — Send
  everything to a small model first; serve high-confidence results directly
  and escalate only the low-confidence tail to the capable model. Works best
  for classification and extraction where a confidence score exists. If the
  cheap model handles 70% confidently you remove 70% of expensive-model calls,
  paying only the cheap first hop on the remaining 30%. The failure mode is
  threshold calibration — too strict over-escalates, too loose ships bad
  answers.

- **Fallback chains plus circuit breakers are the reliability layer** — Define
  a cascade: primary down → backup; backup rate-limited → third option.
  Crucially, add a circuit breaker so a model that is timing out on most
  requests stops receiving traffic during a cooldown rather than absorbing
  repeated failures, with a trial period to detect recovery. Defaulting *up*
  to a more capable model during a failure is usually an acceptable degradation.

- **Placement is a trust decision, not just a latency one** — Client-side
  routing is fastest but clients are untrusted, so pricing tiers, budgets and
  compliance rules cannot be enforced there. Backend routing gives control,
  observability and security at the cost of an extra hop worth roughly
  100–300ms for global users. The common production shape is hybrid: client or
  edge for simple latency-critical choices, backend for anything
  trust-bearing, with server-side validation able to override the client.

- **Routing observability has its own required fields** — Every request should
  log the chosen model, the reason, the matched rule or threshold, and a
  request ID; distributed tracing (OpenTelemetry is named) is what makes a
  path spanning edge, backend and fallback layers debuggable. Track cost per
  request, latency percentiles, error rate and retry frequency *per route* so
  you can tell which routes help. Add plain-language explanations for
  non-engineers — logs alone do not align routing with business goals.

- **The named anti-patterns** — Over-optimising early (building routing at
  $500/month spend); cutting cost so aggressively that quality drops, which
  shows up as retries, dissatisfaction and churn rather than savings; shipping
  routes without fallbacks; ignoring the latency the router itself adds; and
  not testing routing logic — it is code and needs rule validation, simulated
  failures, edge cases, and checks that routing metadata propagates.

- **Buy-versus-build has quantified costs** — Build-your-own is "a few hundred
  lines" on an existing backend and gives deep integration with your user DB,
  feature flags and cost tracking, at a maintenance cost. Martian adds roughly
  20–50ms plus volume pricing for routing, fallbacks and per-request tracing.
  Portkey's content-based semantic routing adds roughly 50–100ms as part of a
  fuller gateway (prompt management, caching, security). OpenRouter is one API
  for many providers at a 10–20% markup with less control. LiteLLM Proxy is
  self-hosted YAML-configured routing with no per-request fee but operational
  burden. Anthropic's Prompt Routing needs no infrastructure but is Claude-only
  and opaque. OctoRouter does semantic routing with local ONNX embeddings (no
  external call), per-provider budgets, Redis-backed state across instances,
  circuit breakers with automatic fallback, and zero-downtime config updates.

## When to apply / trade-offs

Apply routing when you can name the pain: LLM cost growing faster than
revenue, latency variance hurting conversion, genuinely divergent use cases
served by one model, a provider outage that took you down, or features you
are declining to build because the economics do not work. Absent those, the
article is emphatic that routing is premature optimisation — at 1,000
requests a day and a few hundred dollars a month, and for early-stage
products still finding product-market fit, low-volume features, or systems
where every request has the same complexity profile, engineering time beats
the savings. The costs of adopting it are real and compounding: extra
latency from the routing hop itself, a new class of failure modes, threshold
calibration work, opacity unless you invest in routing-specific logging and
tracing, and a test surface that most teams forget exists. Note also that
complexity prediction need not be perfect — an 80%-accurate classifier still
pays off at scale — so do not let perfectionism about classification block a
useful rule-based v1.

## Fidelity check

1. Claim: five to ten simple rules cover roughly 80% of routing needs, using
   signals like input length, user tier, endpoint and time of day. Support:
   the capture states that most teams discover they can handle 80 percent of
   routing needs with five to ten simple rules and names exactly those four
   signals as capturing most meaningful differences between requests.
2. Claim: confidence-based routing removing 70% of expensive-model calls when
   the cheap model answers 70% confidently. Support: the capture gives that
   arithmetic directly, including that the overhead is the initial cheap
   request for the remaining 30 percent, and cites a 95-percent threshold as
   an example for a support-ticket classifier.
3. Claim: backend routing costs roughly 100–300ms for global users, and
   client-side routing cannot enforce trust decisions. Support: the capture
   states the extra hop can add 100 to 300 milliseconds for global users and
   says clients are untrusted so pricing tiers, compliance rules and budgets
   cannot be enforced in client code, with hybrid as the common shape.
