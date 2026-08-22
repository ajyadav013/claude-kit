# Digest: Design A Rate Limiter

- **Source:** https://x.com/Harry_The_Nerd/status/2045533839649624096
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Reject-with-guidance contract (429 + Retry-After)
The limiter's externally visible behavior is a three-part contract: count each caller's requests inside a time window, pass them through while under the quota, and answer over-quota traffic with HTTP 429 plus a Retry-After header carrying the number of seconds until the caller may retry. Emitting the retry hint matters — it converts blind client retry storms into well-behaved backoff, because the server tells clients precisely when capacity returns. Use this shape any time you build throttling that third parties consume; the trade-off is that you commit to computing an accurate reset time, which is trivial for fixed windows but requires more care for sliding or bucket schemes.

### Enforce at the edge, before the services
Placement is architectural, not incidental: the check must run at or before the API gateway — commonly as gateway middleware — never behind it. The rationale is that a limiter exists to shed load before it consumes downstream resources; once a request has traversed the gateway into a service, the cost you were trying to avoid has already been paid. The middleware arrangement gives the gateway two responsibilities (throttle, then route). Trade-off: the gateway becomes a policy chokepoint, so its latency and availability characteristics now bound the whole platform.

### Centralized counting (why per-node counters fail)
The naive design — an in-process map from user ID to a counter on each server — silently breaks under horizontal scaling. With N servers behind a load balancer, one user's requests fan out so each node observes only a fraction of the true total; a user who has issued three requests can look like they issued one on every node, and the limit is effectively multiplied by the fleet size. The fix is structural: the counter must live in one shared store that every enforcement point consults. When to apply: any stateful admission-control decision in a multi-instance deployment. Trade-off: you introduce a network hop and a shared dependency on the hot path.

### Redis atomic counter with TTL
The shared store of choice is Redis, because three properties line up exactly with the problem: INCR gives race-free atomic increments without application-level locking; a TTL on the key makes windows self-expiring, eliminating any cleanup job; and in-memory reads keep the added per-request cost under a millisecond. The decision flow per request: if the caller's counter key is absent, create it at 1 with a 60-second TTL and admit; if present, atomically increment and compare against the limit — at or under admits, over rejects with 429. Trade-off: Redis becomes critical-path infrastructure whose loss you must plan for (see fail-open below).

### Two-store split: ephemeral counters vs. persistent rules
The design separates state by lifetime. Redis holds the volatile data — counters and request timestamps — and is allowed to be lossy: a Redis restart wipes counters, which is acceptable because they regenerate within one window. A persistent config database (e.g. PostgreSQL) holds the policy: rows keyed by user, tier, and endpoint specifying the max request count and the window length — e.g. a free tier at 100 requests/hour, a premium tier at 10,000, an OTP endpoint at 3 per 10 minutes. At startup the limiter loads these rules into Redis, so runtime decisions never touch the config DB and complete in microseconds. Trade-off: rule changes need a reload/re-cache path, and you accept brief counter amnesia after a Redis restart in exchange for a hot path with zero relational-DB reads.

### Fixed window counting — and its boundary flaw
Time is chopped into aligned buckets (say 60 s each) with the counter zeroed at each boundary. It is the simplest algorithm to implement, but it has a well-known failure mode: a client can pack its full quota into the last seconds of one bucket and another full quota into the first seconds of the next — e.g. five requests in seconds 55–59 and five more in seconds 1–5 — pushing 10 requests through in about 10 seconds, double the intended rate, with both windows individually compliant. Reserve it for non-critical internal tooling where the boundary burst is tolerable.

### Sliding window
Instead of aligned buckets, evaluate the trailing 60 seconds measured from the moment of each request — a window that rolls continuously with time. This removes the boundary exploit entirely and yields the fairest enforcement. The Redis implementation records each request's timestamp in a sorted set and counts members newer than now-minus-window. The article positions this as the most common choice in production and the best default for user-facing APIs. Trade-off: storing per-request timestamps costs more memory and per-check work than a single integer counter.

### Token bucket
Model each caller as a bucket of tokens with two parameters: capacity (e.g. 100) and refill rate (e.g. 10 tokens/second). Each admitted request spends one token; an empty bucket means rejection with 429. Its distinguishing property is deliberate burst tolerance: an idle caller accumulates a full bucket and may legitimately fire the entire capacity at once — a good fit where bursts are expected and valid, such as a developer API client running a batch job. The article cites Stripe and AWS API Gateway as users of this scheme. Trade-off: the burst allowance that makes it friendly to legitimate spiky clients also means downstream sees uneven load.

### Leaky bucket
Invert the token model: incoming requests enter a bounded queue and are drained at a fixed rate (e.g. 10 requests/second) regardless of arrival rate; when the queue is full, new arrivals are dropped. The output is perfectly smooth, which is the point — choose it when a downstream dependency needs a steady, capped flow it can never be spiked past, such as payment or billing processors. Trade-off: legitimate bursts get delayed in the queue or dropped outright, which callers can perceive as unfair.

### Algorithm selection heuristic
The article's decision table: fixed window for simple, non-critical internal tools; sliding window as the fairness default for user-facing APIs; token bucket when bursty usage is a legitimate pattern (developer/batch APIs); leaky bucket when the priority is protecting a downstream system that requires constant throughput (payments). The underlying axis is whose experience you optimize — the caller (allow bursts) or the callee (smooth output).

### Horizontal scaling via keyspace sharding
Both tiers scale out independently: stateless limiter/gateway instances multiply horizontally, and Redis grows through Redis Cluster, which partitions the key space across nodes so different users' counters land on different shards. Because each user's state is a single key, sharding by key distributes load evenly with no cross-node coordination and no single hot bottleneck. Trade-off: cluster operation adds topology management, and any future multi-key logic must respect slot boundaries.

### Latency as a first-class requirement
The limiter executes on every single request, so its cost is added to every user interaction — a slow limiter degrades the entire system uniformly. The budget discipline in this design: sub-millisecond Redis checks, plus the startup rule-caching described above so no request ever waits on the config database. Target state: the limiter's presence is imperceptible to end users. This generalizes to any middleware placed on the universal hot path — measure and cap its overhead explicitly.

### Fail-open vs. fail-closed on store outage
When the central store dies, there are exactly two coherent policies: fail open (admit everything — the platform keeps serving but is temporarily unprotected) or fail closed (reject everything — protection is preserved but the platform is effectively down for all users). The article reports that most production systems pick fail open, reasoning that a short interval of unthrottled traffic is a smaller harm than a total outage. The engineering takeaway is to make this choice deliberately and encode it, rather than letting exception-handling defaults decide for you; the right answer flips for abuse-sensitive endpoints (auth, OTP) where fail closed may be safer.

## Not absorbed

- Series branding ("High-Level Design Question-Based Series #3") — interview-prep framing, not engineering content.
- Opening hype sentence promising a fast/fair/production-ready design — motivational framing only.
- Closing sign-off addressing readers ("legends", cheers) — personal flourish.
- Post timestamp, view count, and engagement numbers in the capture — platform metadata, not article content.

## Fidelity check

**Post count in capture:** 1 (a single long-form article post; `postCount: 1` in the capture JSON, no `---AUTHOR-POST-BREAK---` separators present).

**Article outline (author's section order):**
1. Intro — what a rate limiter protects against
2. Functional requirements (three behaviors; 429 + Retry-After)
3. Where does it sit exactly? (gateway placement)
4. The counting problem — why a single server isn't enough
5. Redis is the right tool here (INCR / TTL / speed + decision flow)
6. The database layer — two stores (Redis primary, Config DB persistent)
7. The four windowing algorithms
   - 1. Fixed window
   - 2. Sliding window
   - 3. Token bucket
   - 4. Leaky bucket
8. Which one to use? (selection table)
9. Non-functional requirements
   - Scalability (Redis Cluster)
   - Latency (critical path, <1 ms)
   - Availability (fail open vs. fail closed)
10. Sign-off

**Pattern-to-section citations:**
- Reject-with-guidance contract (429 + Retry-After) — from "Functional requirements" (section 2).
- Enforce at the edge, before the services — from "Where does it sit exactly?" (section 3).
- Centralized counting (why per-node counters fail) — from "The counting problem" (section 4).
- Redis atomic counter with TTL — from "Redis is the right tool here" (section 5).
- Two-store split: ephemeral counters vs. persistent rules — from "The database layer - two stores" (section 6).
- Fixed window counting — from "The four windowing algorithms", subsection 1 (section 7).
- Sliding window — from "The four windowing algorithms", subsection 2 (section 7).
- Token bucket — from "The four windowing algorithms", subsection 3 (section 7).
- Leaky bucket — from "The four windowing algorithms", subsection 4 (section 7).
- Algorithm selection heuristic — from "Which one to use?" (section 8).
- Horizontal scaling via keyspace sharding — from "Non-functional requirements / Scalability" (section 9).
- Latency as a first-class requirement — from "Non-functional requirements / Latency" (section 9).
- Fail-open vs. fail-closed on store outage — from "Non-functional requirements / Availability" (section 9).
