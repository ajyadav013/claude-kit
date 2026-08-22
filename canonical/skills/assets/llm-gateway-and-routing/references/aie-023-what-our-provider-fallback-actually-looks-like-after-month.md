---
source: https://www.reddit.com/r/LLMDevs/comments/1ulbef7/what_our_provider_fallback_actually_looks_like/
author: Reddit r/LLMDevs practitioner thread (u/Few_Sort8392 and repliers)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Provider failover starts with classifying the failure, not retrying harder

## What it adds beyond the primary

This is field experience, not vendor documentation, and it names three
distinctions the kit currently has no vocabulary for. First, a rate-limit
rejection can arrive while the monthly quota dashboard still shows headroom,
because the per-minute burst ceiling and the monthly ceiling are separate
limits; a `retry-after` header is the signal that you are being throttled
rather than exhausted, and retrying harder against the same endpoint lengthens
the outage instead of ending it. Second, the thread argues for a failure
taxonomy — throttle, timeout, 5xx, content refusal, malformed or
schema-invalid response, interrupted stream — where each class gets an opposite
policy (honor `retry-after` with jitter on a throttle; fail over quickly on a
timeout; never spend a retry on a content refusal, since the same input
produces the same refusal), and for keeping the retry budget (same provider,
another attempt) separate from the fallback budget (a different
provider/model). Third, it treats failover as having distinct safe points:
before the first token is emitted switching is clean, mid-stream you must
either restart the response or abort rather than silently splice a second
provider into one transcript, and after a tool call has executed switching
usually means redoing work. It also raises two economics points the kit does
not make anywhere: fallback fires precisely at peak, so an unpriced fallback
routes the most expensive traffic to the more expensive backup and you learn
about it from the invoice; and consolidating N provider integrations behind one
router trades many failure points for one new single point of failure while
often forfeiting provider-native prompt caching and batch discounts.

## Primary source for this cluster

No primary digest for the `model-routing-fallback` cluster exists on disk yet
(the digest directory currently holds only the harness-engineering,
context-engineering, and observability clusters). This stub stands alone until
a primary lands; it should be re-checked for redundancy at that point.

## Fidelity check

1. Claim: a rate-limit rejection can arrive while the quota dashboard still
   shows availability. Support: the capture describes a Friday traffic spike
   where the dashboard showed quota remaining but the API kept returning a
   rate-limit error carrying a retry-after header, and names the monthly quota
   and the per-minute rate limit as two distinct ceilings.
