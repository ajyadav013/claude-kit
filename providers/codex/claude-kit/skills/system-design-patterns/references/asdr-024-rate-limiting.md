---
source: https://blog.algomaster.io/p/rate-limiting-algorithms-explained-with-code
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Choosing among the five classic rate-limiting algorithms

## What it teaches

A comparative tour of the five standard algorithms for capping request rates —
token bucket, leaky bucket, fixed window counter, sliding window log, and
sliding window counter — with the pros/cons that drive selection. The framing
is protective: rate limiting exists to keep one client or user from
overwhelming a service, and the algorithms differ mainly in how they treat
bursts, how much memory they need, and how accurate they are at window edges.
(Original post links to reference implementations; per license rules none are
reproduced here — designs described in prose only.)

## Key patterns & decisions

- **Token bucket for burst tolerance**: tokens refill at a fixed rate into a
  capped bucket; each request spends a token and is dropped when none remain.
  Simple, and deliberately allows short spikes up to bucket capacity — but
  per-user buckets multiply memory, and output is not perfectly smooth.
- **Leaky bucket for smoothing**: requests queue in a bucket that drains at a
  constant rate; overflow is discarded. Produces a steady, predictable
  processing rate at the cost of rejecting bursts outright and slightly more
  implementation complexity than token bucket.
- **Fixed window counter for simplicity**: count requests per fixed time
  slice and deny once the count hits the limit. Easiest to build and explain,
  but the notorious boundary problem lets a client concentrate traffic at the
  end of one window and the start of the next, briefly doubling the effective
  rate.
- **Sliding window log for precision**: keep a timestamp per request, evict
  entries older than the window, and admit only while the remaining count is
  under the limit. Exact — no edge artifacts — but memory and scan cost grow
  with traffic, so it suits low-volume APIs.
- **Sliding window counter as the pragmatic hybrid**: keep only two counters
  (previous and current window) and estimate the in-window count by weighting
  the previous window's count by its remaining overlap fraction before adding
  the current count. Near-log accuracy at near-fixed-window memory cost;
  slightly trickier to implement.
- **Advertise limits via response headers**: publish limits/remaining quota to
  API consumers so their clients can implement sane retry and backoff instead
  of hammering blindly.
- **Selection is workload-driven**: pick based on system scale, traffic
  burstiness, and how fine-grained the control must be — there is no
  universally best algorithm.

## When to apply / trade-offs

Token bucket when legitimate bursts should pass (interactive clients, CLIs);
leaky bucket when a downstream needs constant-rate protection; fixed window
when simplicity beats precision and edge-doubling is tolerable; sliding log
when accuracy is paramount and volume is low; sliding counter as the default
for high-volume APIs wanting accuracy without per-request storage. A reader
comment adds a worthwhile nuance: fixed windows anchored to first-request
arrival (rather than calendar boundaries) blunt the boundary-burst critique,
and the "bursts are bad in fixed window but good in token bucket" framing in
most articles is somewhat contradictory — a reminder that burst tolerance is a
policy choice, not an inherent flaw. Another comment notes that leak-on-request
implementations of leaky bucket can starve queued requests during long idle
gaps, arguing for timer-driven draining.

## Fidelity check

1. *Claim: fixed window counters can briefly admit double the intended rate.*
   The capture's cons for fixed window state that bursts straddling a window
   boundary are handled poorly and can allow twice the rate at the edges.
2. *Claim: the sliding window counter weights the previous window by overlap.*
   The capture explains that when 75% of the current window has elapsed, the
   remaining 25% weight comes from the previous window's count, and the new
   request is admitted only if the weighted total stays under the limit.
3. *Claim: sliding window log is accurate but memory-heavy.* The capture lists
   "very accurate, no rough edges" as its strength and flags memory intensity
   plus timestamp storage/search as the reason it fits low-volume APIs.
