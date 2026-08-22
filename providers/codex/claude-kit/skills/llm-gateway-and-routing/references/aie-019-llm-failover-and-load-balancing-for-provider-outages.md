---
source: https://www.truefoundry.com/blog/llm-failover-load-balancing-provider-outages
author: Boyu Wang (TrueFoundry)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Model-provider reliability is a routing-layer concern, not an app concern

## What it teaches
Any application that calls a single model provider directly inherits that
provider's worst day as its own; the fix is a reliability layer that sits
between the app and every provider. The piece builds that layer in order:
first a taxonomy separating hard 5xx errors, 429 rate limits, silent latency
degradation, mid-stream drops, and safety-filter refusals — each with a
different correct response — then retries with exponential backoff and jitter
that honour the provider's own timing signal, then ordered fallback chains
across independent failure domains, then health-aware load balancing, then
circuit breakers that fail fast instead of letting a dead dependency drain
your own queues. It ends on the two honest hard parts: failover changes your
output (a different model formats, refuses, and reasons differently), and
mid-stream failover has no clean answer once tokens are already on the user's
screen. The argument for centralising all of this at a gateway is that only
the gateway sees every provider and key, and per-service implementations
drift into five subtly different, subtly wrong retry policies.

## Key patterns & decisions
- **Classify before you react** — the common mistake is treating everything as
  "error, retry". Hard errors get a brief retry then a fallback; 429s get
  header-driven backoff and a shift to a different quota pool; slow-but-OK
  responses need a timeout tied to your SLO plus hedging or fallback.
- **Content-filter refusals are non-retryable by construction** — a safety
  rejection is a property of the request, not a transient fault. Retrying it
  burns latency and money, and another provider usually refuses too. It
  belongs on a policy-remediation path (rewrite the prompt, ask the user,
  route to a safer flow), not in the failover chain.
- **Retries must obey the server's own signal** — exponential backoff, jitter,
  and honouring `Retry-After` (or the remaining/reset headers where that is
  the provider's contract). Synchronised immediate retries during a 429 storm
  sustain the very overload you are trying to escape.
- **Keep the retry count small — two or three — then hand off** — more attempts
  against a genuinely-down provider only delay the fallback that would have
  succeeded, while adding load at the worst moment.
- **Two fallback axes with different blast radii** — an alternate region or
  deployment inside the same provider is cheap but shares a failure domain;
  crossing to a different vendor gives genuinely independent infrastructure.
  A robust chain tries the cheap one first, then crosses vendors.
- **Failover buys availability by spending fidelity** — the fallback model may
  format, refuse, or reason differently, so the user's answer during a
  failover is not the answer the primary would have given. Validate fallback
  output against the same schema as the primary and keep prompts portable.
- **Filter the fallback set by policy before cost or health logic runs** — data
  residency, customer allowlists, regulated-data rules, contractual terms, and
  tool/schema support can each disqualify a candidate. A region-restricted
  route cannot silently fail over to a global endpoint just because it is up.
- **Headroom comes from independent quota pools, not extra keys** — providers
  commonly enforce limits at the organisation, project, or model-family level,
  so more keys under one org share one pool. Real capacity comes from separate
  providers, regions, projects, or accounts, and the balancer should route
  against remaining capacity reported in rate-limit headers.
- **Circuit breakers convert a full timeout into a fast rejection** — closed,
  then open after an error-rate window or N consecutive failures, then
  half-open with a small probe. Without one, every request to a dead provider
  waits out its timeout and the provider's outage becomes your queue backup.
- **Hedging is a tail-latency tool with a cost multiplier** — firing a duplicate
  request near the p95 delay cuts p99, but you pay for two calls, cancellation
  may still bill partial tokens, and duplicated side effects matter for
  tool-calling agents. It is not a default.
- **Streaming failover is a per-path decision, not a global setting** — buffer
  server-side (clean failover, loses perceived latency), accept visible
  restarts, or confirm liveness with a non-streamed first token before
  committing. A customer chat and a batch agent should choose differently.

## When to apply / trade-offs
Apply this the moment a model call sits on a path that has to succeed, and
especially once more than one service in the org calls models — that is the
point where per-service retry logic starts diverging. The costs are real:
maintaining a second provider means portable prompts and per-model output
validation, hedging multiplies spend, circuit breakers can trip falsely and
shed traffic a healthy backend could have served, and buffering streams gives
back the latency benefit that motivated streaming. The suggested numbers
(two-to-three retries, hedge near p95, per-hop timeout at the healthy
backend's p95–p99) are stated as starting points to tune against your own
SLOs, not constants. Skip the heavy machinery for internal, batch, or
best-effort paths where a retry-and-give-up is a fine answer, and do not
reach for cross-provider failover at all when policy or contract pins the
workload to one vendor — there the honest design is within-provider
redundancy plus a clear degradation story.

## Fidelity check
1. Claim: content-filter refusals should be classified non-retryable and sent
   to a remediation path. Support: the capture's failure-mode table gives
   "4xx from a safety filter" the response of surfacing to a policy
   remediation path rather than blindly retrying, and the following prose
   calls this the row teams most often get wrong.
2. Claim: extra API keys under one organisation do not multiply rate-limit
   headroom. Support: the load-balancing section states limits are commonly
   enforced at the organisation, project, or model-family level, cites OpenAI
   as saying additional keys under the same organisation do not raise limits,
   and repeats the point in the closing notes.
3. Claim: hedging fires near p95 and can still bill for the cancelled call.
   Support: the hedged-requests section says to fire only after a delay tuned
   around the p95 and warns that a cancelled call may still bill for partial
   tokens depending on provider and generation progress; the defaults table
   lists hedge delay as "near p95".
