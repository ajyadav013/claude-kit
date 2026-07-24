---
name: system-design-patterns
description: HLD building blocks — back-of-envelope estimation, rate limiting, load balancing, CDN, caching hierarchy, unique IDs, feed/notification fan-out, chat, microservice boundaries. Use when designing or reviewing a system architecture before code.
---

A catalog of reusable high-level-design building blocks — how to size a workload, shape its traffic, cache its hot set, generate its IDs, fan out its writes, and draw its service boundaries — with a composite map showing how real systems assemble them.

## When to use

- Designing a new service or feature and deciding which architecture the workload actually justifies
- Reviewing a spec or HLD for missing capacity math, premature sharding, or misplaced caching
- Choosing a rate-limiting algorithm, load-balancing strategy, or CDN invalidation approach
- Picking an ID scheme (Base62, UUID, Snowflake-style) for a new entity or event stream
- Building anything with fan-out: notifications, social feeds, group chat, typeahead
- Modeling time-bounded inventory (bookings, reservations, holds) or blob-heavy records
- Debating whether to split a service — or diagnosing a distributed monolith
- Preparing the design section of a spec for the `spec-driven-development` or `/sdlc` pipeline

## Back-of-envelope estimation and read/write asymmetry

Run the numbers before drawing boxes. The estimate does not need precision — it needs the order of magnitude and the read/write ratio, because those two numbers decide which scaling machinery is even worth discussing.

1. **Use rounded constants for mental math.** Treat a day as ~100k seconds. Getting within 2x is enough; getting the exponent wrong is not. The canonical shortener estimate:

    ```text
    10M DAU, 1B URLs over the system lifetime, day ≈ 100k s
    → ~10,000 req/s total
    → writes ~1%  ≈   100 req/s
    → reads ~99%  ≈ 9,900 req/s
    ⇒ read-dominated: caching + replicas + a read/write service
      split are earned; sharding is not (yet)
    ```

2. **Split the total by the read/write ratio, then let the ratio drive the design.**
    - A link shortener at 99% reads earns caching layers, read replicas, and a read/write service split.
    - A social platform where users reply and vote as much as they scroll (a ~3:1 ratio) must invest equally in write buffering and asynchronous fan-out.
    - A commerce system whose *storage* is dominated by write-once media can still have its real problem elsewhere: write *consistency* under synchronized purchase spikes.
    - The technique is the same every time: identify the single dominant load dimension and let it dictate the architecture's center of gravity.

3. **Scale reads in a strict order: cache, then replicas, then shard last.**
    - A cache with LRU eviction organically retains the hot set (a Pareto-shaped 20% of items drawing 80% of traffic).
    - Cache misses fall to read replicas.
    - Shard the primary only when *write* volume itself is the bottleneck — reaching for sharding first is the classic premature move.

4. **Split write and read services behind a gateway when asymmetry is extreme.** A shortener service that mints keys and a redirector service that resolves them scale independently; the high-volume read path gets its own cache and fleet without ever touching the write path.

5. **Derive fleet size from connection or throughput math, not intuition.** 20% of 10M DAU online at once is ~2M live sockets; at ~50k connections per server that is a ~40-server fleet. Numbers like these justify (or kill) whole design branches before any code exists.

## Rate limiting

1. **The external contract is three-part:**
    - count each caller's requests inside a time window;
    - admit traffic under the quota;
    - answer over-quota traffic with HTTP 429 plus a `Retry-After` header stating when capacity returns — the hint converts blind client retry storms into well-behaved backoff.

2. **Enforce at the edge — at or before the API gateway, never behind it.** A limiter exists to shed load before it consumes downstream resources; once a request has crossed the gateway, the cost you were avoiding is already paid. The gateway becomes a policy chokepoint, so the check itself must stay sub-millisecond.

3. **Counters must be centralized.** A per-node in-process counter silently multiplies the limit by the fleet size — behind a balancer, each server sees only its slice of one user's traffic. Keep the counter in one shared store: an atomic increment plus a TTL makes windows self-expiring with no cleanup job, and in-memory reads keep the added cost under a millisecond. Accept the network hop as the price of correctness.

4. **Split state by lifetime.**
    - Volatile counters live in the fast store and are allowed to be lossy — they regenerate within one window after a restart.
    - Persistent policy lives in a config database: rows keyed by user, tier, and endpoint (free at 100/hour, premium at 10,000/hour, OTP at 3 per 10 minutes).
    - Load the rules into the fast store at startup so no request ever waits on the policy database.

5. **Know the four algorithms and their selection axis:**
    - **Fixed window** — aligned buckets, counter zeroed at each boundary. Simplest, but a caller can pack a full quota into the last seconds of one bucket and another into the first seconds of the next, doubling the effective rate. Reserve for non-critical internal tooling.
    - **Sliding window** — evaluate the trailing window from each request's moment (per-request timestamps in a sorted structure). Removes the boundary exploit; the fairest default for user-facing APIs, at the cost of timestamp storage per request.
    - **Token bucket** — a capacity plus a refill rate; an idle caller accumulates a full bucket and may legitimately burst it all at once. Fits developer and batch APIs where spikes are valid traffic; downstream sees uneven load.
    - **Leaky bucket** — a bounded queue drained at a fixed rate; the output is perfectly smooth. Choose when a downstream dependency (payments, billing) must never be spiked past a constant throughput; legitimate bursts get delayed or dropped.

    The selection axis is whose experience you optimize: the caller (allow bursts) or the callee (smooth output).

6. **Decide fail-open vs fail-closed deliberately.** When the counter store dies there are exactly two coherent policies: admit everything (briefly unprotected, but serving) or reject everything (protected, but down). Most production systems fail open — encode the choice explicitly rather than letting exception-handling defaults decide, and flip to fail-closed for abuse-sensitive endpoints (auth, OTP).

## Load balancing

1. **L4 vs L7 is the first split.** Transport-layer balancing forwards on IP and port without opening the payload — extremely fast. Application-layer balancing parses the request and can steer on path, header, or cookie (an API pool, a media pool, a payments pool per path prefix). The production norm: L7 for application traffic, L4 where raw throughput matters.

2. **Match the algorithm to the fleet and the workload:**
    - **Round-robin** — cycle the server list in fixed order; right when every backend has identical capacity, blind to machine specs and in-flight work.
    - **Weighted round-robin** — per-server weights proportional to hardware, for heterogeneous fleets where equal shares would drown the small machines.
    - **IP-hash** — deterministic client-to-backend mapping gives affinity for free; beware many clients behind one NAT collapsing onto a single backend, and near-total reshuffles whenever the pool resizes.
    - **Consistent hashing** — servers occupy points on a ring; removing a node remaps only ~1/N of traffic instead of nearly all of it. The standard fix for the reshuffle problem.
    - **Least-connections** — route to the backend with the fewest open connections; the right choice when request cost varies wildly, since order-based schemes stack slow requests on one unlucky machine.

3. **Run both kinds of health check.** Active probes on a short interval catch fully silent hosts; passive observation of live traffic ejects hosts that answer but answer badly. They cover different failure shapes — production systems need both, and the usable pool should shrink gracefully rather than zero out.

4. **Statelessness is the prerequisite.** Every algorithm above is simple only if any backend can serve any request. Externalize sessions to a shared store; if stickiness is unavoidable, keep the user-to-backend map in shared state so every balancer node makes the same routing decision.

5. **Present one stable entry point.** A floating virtual IP migrates to a surviving balancer node on failure with no client-visible change (DNS round-robin is the simpler, slower-failover alternative). Terminate TLS at the balancer tier so certificates live in one place and backends skip the crypto cost — accepting that traffic behind the edge is then unencrypted unless you re-encrypt.

6. **Respect the critical path.** The balancer sits on every single request, so its routing decision must stay in-memory and add under a millisecond; a slow balancer degrades the entire system uniformly.

## CDN and edge delivery

1. **The cacheability rule is binary.** If every user receives identical bytes (assets, media, public pages), cache it at the edge. Never cache:
    - per-user data — leaking one user's copy to another is a privacy incident;
    - rapidly changing feeds — the cached copy is obsolete almost immediately;
    - mutating requests — writes are never cacheable;
    - personalized pages assembled per viewer.

2. **Route by geography at DNS resolution.** Answer each resolver with the nearest edge's address, so locality is achieved before the first application byte flows — no client or app changes.

3. **Insert a regional tier (origin shield) between edges and origin.** With two tiers, every edge miss worldwide hits the origin independently; with a regional cache, origin load collapses to roughly one fetch per object per region, and each miss warms every layer it passes through on the way back.

4. **Invalidate in three modes, cheapest first:**
    - **TTL** — the baseline; wrong content stays wrong until expiry, so it cannot handle urgent corrections.
    - **Explicit purge** — a delete-now broadcast to every edge node worldwide; immediate but expensive, reserved for emergencies.
    - **URL versioning** — change the object's name (a version parameter or hashed filename) so the new name is a guaranteed miss and the old one ages out naturally. Zero purge traffic; the standard for frontend assets.

5. **Declare policy in `Cache-Control`:**
    - `max-age` — the TTL in seconds;
    - `no-store` — forbid caching entirely (checkout pages, sensitive endpoints);
    - `private` — the browser may cache, shared/CDN caches may not (per-user data);
    - `s-maxage` — a CDN-specific TTL overriding `max-age`, for when the edge and the browser need different lifetimes (a trending feed cached briefly at the edge but not in the browser).

6. **Pull vs push.** Pull-through (fetch-on-miss) is the default and self-managing; the first requester of cold content pays the fill latency. Push-based placement — pre-loading edges from predicted regional demand — is the heavyweight option for scheduled spikes: when a premiere or launch is on the calendar, warm the edges days ahead so the herd arrives to a 100% hit rate, instead of engineering the origin to survive a stampede.

7. **Tier the storage to the role.** Memory at the edge (fastest, only the city's hot set), SSD at the regional tier (a continent's warm set), object storage at origin (unbounded, the source of truth). Long-tail content that never earns edge residency serves from origin at worse latency — a deliberate cost/performance tiering, not a bug.

## Caching hierarchy and selective caching

1. **Cache selectively, because popularity is a power law.** In catalog after catalog, a sliver of items draws almost all traffic — the top ~1% of products serving ~90% of requests, 20% of links drawing 80% of hits. Cache the hot set with generous TTLs; send the cold long tail straight to the database with no cache overhead at all. Caching everything blows memory for no hit-rate gain.

2. **Layer L1 / L2 / L3 to defuse hot keys.** A viral item read by millions concentrates load on one distributed-cache key and saturates the node that owns it. The hierarchy:
    - **L1** — a small in-process LRU on every app server. A viral item is served with zero network hops, and thousands of servers each holding a local copy dissolve the hot-key concentration.
    - **L2** — the shared distributed cache, for warm-but-not-viral content.
    - **L3** — the database of record, touched only on double misses.

    The cost is brief cross-server staleness at L1 — acceptable for content, not for prices. Correctness-sensitive fields get explicit invalidation rather than TTL decay, because staleness windows multiply across layers.

3. **Precompute and serve when computation exceeds the latency budget.** If assembling an answer (a ranked feed, a recommendation list) costs more than the request path can afford, compute it offline and make the hot path a single cache read. The canonical funnel:
    - a cheap **wide stage** (approximate similarity search, collaborative filtering) narrows a 100k-item catalog to ~100 candidates, optimizing recall;
    - an expensive **narrow stage** ranks only the survivors with the heavyweight model, optimizing precision;
    - the top-N result lands in the cache keyed by user, and serving is one read.

    Freshness comes from re-running the pipeline — a slow full rebuild for depth plus a lightweight incremental path for recency — not from computing at read time.

4. **Store IDs, hydrate on read.** Feed and list structures hold item IDs only; the page is hydrated with one batched multi-get against a shared item cache. The latency math is explicit: twenty sequential 1 ms fetches eat a fifth of a 100 ms budget, one batched round trip does not. Misses fall through to the database and write back. Separating "which IDs" from "what content" deduplicates items across every list that references them and keeps the ranking layer decoupled from the object layer.

5. **Every cache needs a bound and a rebuild source.** Cap per-entity structures (a feed at ~1000 entries, trimmed on insert) with the database as full history. For each cache, name the durable source it can be rebuilt from and classify its loss as integrity-critical or annoyance-only — only the former justifies heavier machinery. A lost geo index rebuilt from the location table is an annoyance; a lost seen-items filter briefly shows repeats; neither corrupts anything.

6. **Stampede protection is an implementation concern.** Single-flight locks and probabilistic early recompute for hot keys are covered in `redis-caching-patterns` — this skill decides *what* to cache and *where*; that one decides how to keep it from collapsing.

## URL shortening and unique ID generation

1. **Do not truncate hashes to make short keys.** Hashing the input and keeping the first 6 characters invites prefix collisions between distinct inputs, which then demand detection and retry loops. Base62-encode a monotonic numeric ID instead: uniqueness of the ID transfers directly to the encoded key, and 6 characters over a 62-symbol alphabet (digits plus both letter cases) is a ~56-billion keyspace. The trade: sequential IDs are guessable and require a central ID source.

2. **Score distributed ID schemes against five requirements:** globally unique, time-sortable, numeric (index-friendly), thousands of IDs per second, and low enough latency to never bottleneck the write path. No scheme maxes every axis:
    - **Single auto-increment** — correct and simplest on one box; a single point of failure and a hard throughput ceiling everywhere else, and a second node emitting the same counter collides immediately.
    - **Multi-master step-and-offset** — k servers each stepping by k from distinct offsets interleave collision-free with no runtime coordination; but adding a node means reconfiguring every server live, and IDs are not time-ordered across nodes.
    - **UUIDv4** — coordination-free and operationally trivial; but 128 bits (double the storage and index cost of 64), no time information, and random keys are actively hostile to B-tree indexes — monotonic keys append cleanly, random keys cause page splits that erode write throughput.
    - **Ticket server** — one dedicated central counter service; clean strict sequences at modest scale, but the SPOF returns, every ID costs a network round trip, and running two ticket servers reintroduces the coordination problem you were escaping.
    - **Snowflake-style 64-bit composite** — a sign bit held at zero, 41 bits of milliseconds since a custom epoch (~69 years of headroom), 10 bits of machine ID (1,024 nodes), 12 bits of per-node sequence (4,096 IDs per node per millisecond). Time-sorted for free because the timestamp occupies the high bits; generated in local memory with no network calls.

3. **Snowflake caveats are known and fixable:** a backward clock correction can mint duplicates or past-dated IDs (needs drift detection plus a wait strategy); machine IDs must be assigned across the fleet (a coordination-service job); and ordering is only per-node monotonic — same-millisecond IDs from different machines interleave by machine ID, not true event order.

4. **Default to Snowflake-style at scale; UUID when ordering is irrelevant; a ticket server for a small fixed cluster needing strict sequences.** Mint the ID at the system's entry point so every downstream component — queue, store, receipts — shares one canonical identity and ordering key.

## Notification fan-out

Delivery mechanics (providers, templates, device tokens) live in `notifications-and-messaging`; this section is the fan-out architecture.

1. **One service per delivery channel** (push, email, SMS, in-app). Each channel has its own scaling curve, failure mode, and latency budget; isolation means an SMS surge cannot degrade push delivery, and each channel scales horizontally on its own.

2. **Put a preference-aware router between the queue and the channels.** Unlike a gateway that dispatches on URL, the router carries business logic: suppress channels the user has disabled, force the reliable channel for security-critical messages regardless of stated preference, and redirect to an alternate channel when a primary send fails. Preferences are consulted on every send — cache the lookup; it is the main latency lever in the pipeline.

3. **Buffer bursts in a queue.** A single event fanning out to 10 million users within a second would flatten any synchronous path; events land in the durable log first and channel services drain at their sustainable rate via consumer groups. Durability is the second win: a downed consumer loses nothing — messages wait in the topic until it recovers.

4. **Retry on an escalating schedule, then fall back across channels.** When retries exhaust, switch channels (push fails → email; email fails → SMS) rather than dropping the notification silently. Generic retry/backoff and circuit-breaker discipline is owned by `rules/resilience-engineering.md` — the channel-fallback ladder is the notification-specific layer on top of it.

5. **Make every send idempotent and tracked.** Record three outcomes per message — delivered, opened, failed. Tracking drives the retry/fallback path, feeds product analytics (open rates, send-time optimization, fatigue signals), and accounts for cost on per-message paid channels (SMS, email).

6. **Give latency-critical traffic a bypass lane.** OTPs skip the queue and hit the channel service directly — a small, well-defined synchronous fast path beats tightening latency for the entire async pipeline.

7. **Cap frequency on the recipient, not the trigger source.** At most one promotional message a day no matter how many triggers fire — over-notification drives uninstalls, and no individual producing service can see the aggregate.

8. **Choose coalescing by obligation.** Social events coalesce ("X and 499 others liked…", collapsing a burst window into one push); transactional events (order confirmed, shipped, payment failed) each carry an independent user obligation and must arrive individually. Pick per event class, not per system.

## News-feed fan-out

1. **Fan-out on write (push):** at publish time, insert the post ID into every follower's precomputed feed. Reads are a single cache range-scan — excellent latency. The failure mode is the celebrity problem: one post from a 100M-follower account is 100M cache writes; even at a microsecond each that is ~100 seconds of burst.

2. **Fan-out on read (pull):** assemble the feed at read time by querying every followed account and merging. Writes become trivial; every read becomes a wide fan-out — hundreds of source queries per feed load, at feed-read volume.

3. **Hybrid is the production answer:** push for ordinary accounts, pull for accounts above a follower threshold (~1M), merge the two at read time and cache the merged result briefly. The same shape reappears with a different pivot variable — a community platform fans out small communities on write and large ones (above ~100k members) on read.

4. **Store the feed as a per-user sorted structure** scored by timestamp (chronological ordering for free) or by a composite relevance score. Bound it:
    - cap at ~1000 entries, trimming overflow on insert;
    - the database remains the authoritative full history for anything older;
    - evict idle users' feeds entirely and rebuild from the database on their next login — and skip fan-out for long-idle users in the first place.

5. **Fan out asynchronously behind an event log,** partitioned by author so one author's posts keep their order while workers scale as a consumer group. The user-facing write returns as soon as the post persists and the event is emitted; the short publish-to-appearance delay is the accepted eventual-consistency cost.

6. **Keep a read-time chronological path as both a mode and a failover.** It needs no ranking and no fan-out pipeline — one indexed query across followed accounts — so it doubles as the degradation path when precomputation lags. Building the fallback as a first-class feature is the pattern worth copying.

7. **Paginate with cursors, never offsets.** The cursor is the last item's score or timestamp, letting the read resume the sorted scan in O(log n) regardless of feed depth; offsets degrade as the feed grows.

## Autocomplete and typeahead

1. **The latency budget shapes everything.** A request fires per keystroke, so the round trip must land in ~50–100 ms — which forces the entire read path into memory and all expensive work (frequency counting, ranking) off the request path entirely.

2. **A trie is the lookup structure:** walking the typed prefix costs O(prefix length) regardless of corpus size, and the subtree below the landing node contains exactly the valid completions.

3. **Precompute top-N per node.** A common stem has thousands of completions but the UI shows 5–10, so each node carries a cached frequency-ordered top-N list. Query time does zero ranking — it reads a precomputed list.

4. **Never mutate the live structure.** At search-engine scale, letting every query update the trie means a hundred thousand writers contending with millions of readers on the hottest structure in the system. Instead:
    - append search events asynchronously to a log;
    - a batch job recounts frequencies every few hours and rebuilds the trie offline;
    - persist the snapshot durably, then swap it into the serving fleet.

    Users read a snapshot hours stale — imperceptible for this workload. Newly trending queries surface one rebuild cycle late; that is the accepted trade for read-path stability.

5. **Shard by traffic share, not alphabet.** Letter popularity is wildly skewed — one hot prefix range can justify a dedicated shard while a dozen quiet ones share a node. A coordination service owns the prefix-to-shard map so shards can be rebalanced without client changes.

6. **The lightweight alternative:** for smaller corpora, a prefix-keyed sorted set scored by historical query frequency, read with a top-N range call and rebuilt periodically from query logs, delivers the same precompute-and-serve shape without the trie machinery.

## Chat and real-time sync

1. **Size the fleet from the concurrency math:**

    ```text
    10M DAU × 50 msg/user/day = 500M msg/day ≈ 5,000 msg/s
    ~20% online concurrently  ≈ 2M live sockets
    ÷ ~50k connections/server ≈ 40-server socket fleet
    ```

2. **Choose the connection model from the delivery direction.** Server-initiated delivery makes request/response the wrong shape: short polling at scale is ruinous (10M clients on a 5-second poll is ~2M req/s of mostly empty asks), and long polling remains half-duplex and churn-heavy. A persistent full-duplex socket lets the server push the instant a message lands — at the cost of stateful servers sized by connection count.

3. **Store-and-forward: persist durably before any delivery attempt.** Write-first, deliver-second is the invariant that makes a recipient device dying mid-push a non-event. Never optimistically skip the write to shave latency; slightly slower delivery outranks any risk of loss.

4. **Order with time-sortable IDs minted at ingest** (Snowflake-style — see the ID section), so queue, store, and receipts share one canonical identity and ordering key across the fleet.

5. **Stage the acknowledgements to pipeline stages, not promises:**
    - *sent* — the system has custody (ID minted, event queued);
    - *delivered* — the recipient's device acked over its socket;
    - *read* — the recipient opened the conversation and the client emitted a read event.

6. **Offline delivery is a catch-up read, not a retry queue.** If presence says the recipient is offline, the message already sits in the store; trigger a push notification, and on reconnect the client pulls the backlog and acks then.

7. **Route across a stateful fleet with a per-user pub/sub channel.** Each socket server subscribes to channels for its own connected users; a delivery worker publishes to the recipient's channel and whichever server holds the socket forwards it. Past a few dozen servers, move to deterministic routing (consistent-hashing users to servers). On server death, clients reconnect elsewhere and connection state is *rebuilt* (re-subscribe, reload the recent window), not replicated.

8. **Presence is a heartbeat plus TTL.** The client pings every N seconds; the server refreshes a per-user key with a ~3N TTL. Missed heartbeats simply expire the key — offline with no explicit logout path, "last seen" for free from the final heartbeat, and up to one TTL window of staleness that every major chat product accepts.

9. **Group fan-out: one stored copy, expand at delivery.** Write the message once under the conversation ID, fetch membership, push to online members and notify offline ones. Cap group size (~1k) — beyond that, per-member fan-out on write becomes a thundering herd and the design must switch to fan-out on read or a broadcast tree.

10. **Media never transits the message pipeline.** Clients upload via pre-signed URLs directly to object storage; the message carries only the URL and metadata; recipients fetch from the CDN edge, keeping socket servers free of large payloads.

## Data-modeling building blocks

1. **Separate metadata from blobs.** Never store large payloads in the relational database — big blobs degrade it. The row holds a pointer (owner, key, object-storage URL, timestamps); the content lives in object storage. The database stays small and fast; the read becomes a two-hop fetch (metadata, then blob).

2. **Make expiry a first-class column, and purge both stores.** Time-limited records carry `expires_at` in the schema, and a background job deletes lapsed entries from *both* the database and the object store — removing the row without the blob leaks storage; removing the blob without the row dangles pointers. Expiry must be enforced consistently across every layer that holds the data.

3. **Select the store from the query shape, not fashion:**
    - Pure point lookups by key — a small relational table or KV store is enough; a "web-scale" database adds nothing to a lookup workload.
    - "One conversation, chronological, paginated" — the natural shape of a wide-column store partitioned by conversation, clustered by time.
    - Multi-hop traversals (mutuals, suggestions) — a graph store; first-degree edges stay a plain indexed join table, because a follow is an insert and a first-degree lookup is an index scan.
    - Heterogeneous per-category attributes — a semi-structured JSON column beats table-per-category proliferation.
    - Attributes that must be *filtered on* — one indexed row per (entity, attribute), never a JSON array; conjunctive filters ("pool AND parking") become ordinary indexed WHERE clauses.

4. **Two-phase holds with expiring reservations.** When commitment involves a slow external step (payment, human confirmation), never hold a lock across it:
    - Phase one is a millisecond-scale transaction flipping the target to `reserved` with an expiry timestamp — a ~10–15 minute TTL and a status enum (reserved / confirmed / released).
    - Phase two converts the reservation on success or releases it on failure.
    - A background sweeper returns lapsed holds to available every minute or so.

    Inventory is briefly withheld from other buyers — the price of dropping lock hold time from minutes to milliseconds.

5. **Calendar-table inventory for date-range booking.** Materialize availability as one row per unit per day — status enum, per-date price, optional booking reference:
    - A range check becomes "count available rows in the window and compare to nights requested."
    - Owner-blocked dates and per-date (weekend, event) pricing fall out for free.
    - Row counts explode (millions of units × 365 days), but the composite key keeps every check an index scan.
    - Guard the authoritative path with the database's own row locks (`SELECT … FOR UPDATE` over the date rows): if the truth already lives in the relational store, native transactional locking is simpler and strictly correct versus bolting a separate distributed lock alongside it.
    - Serve the high-QPS *search* path from an approximate fast structure — per-month bitmaps, one bit per day, combined with a bitwise AND across the range. Slight staleness is fine precisely because the final booking re-checks under the lock. Spend consistency only where the invariant demands it.

## Service decomposition and microservice boundaries

1. **A service is a microservice only when all four criteria hold simultaneously:**
    - it releases on its own, with no cross-service release coordination;
    - it is the sole owner of its data store — nothing else queries its tables;
    - its boundary is one business capability (payments, inventory, notifications), not a technical tier;
    - one team owns it end to end, operations and on-call included.

    Use this as the acceptance test when carving out or reviewing any service boundary.

2. **Violate any one criterion and you have a distributed monolith** — monolith-grade coupling plus network-grade failure modes. Two services sharing a table, or releases that ship in lockstep, fail the test. Run this diagnostic before claiming an architecture "has microservices."

3. **Four properties are orthogonal to the architecture** and never justify a split:
    - **Size** — a valid service can be hundreds or tens of thousands of lines; the boundary is the criterion, not the line count.
    - **Containers** — packaging, not architecture; monoliths run fine in containers and microservices on bare metal.
    - **Repo layout** — monorepo vs many repos is an organizational choice.
    - **Tables** — one-service-per-table is the worst split of all: it builds a distributed database with added network hops. Split along business capabilities, never along schemas.

4. **The benefits are exactly three, purchased with a concrete cost ledger.** The triad: independent deployment, independent scaling, independent ownership. The ledger, all of which must be designed for up front:
    - in-process calls become remote calls with new failure classes;
    - partial failure replaces all-or-nothing, so degradation paths must be explicit;
    - cross-service transactions disappear — eventual consistency must be reasoned about, not assumed;
    - one stack trace becomes distributed tracing, correlation IDs, and log aggregation;
    - every deployable multiplies pipelines, monitoring, and infrastructure spend.

    The ledger is the entry price, not a reason to refuse — the decision is whether the triad is worth it *for this system*.

5. **Conway's Law is a design input, not trivia.** The architecture will mirror the org's communication structure regardless of intent. If three teams must constantly coordinate to ship anything, cutting their code into three services relocates the coordination into the network layer — it does not remove it. Design team boundaries deliberately first; never use service extraction as a fix for organizational coupling.

6. **Adopt when deploy contention justifies the ledger** — typically a larger organization where multiple teams block each other's releases. A small team on an early product usually should not pay the price. The runtime failure patterns the ledger forces on you (timeouts, retries, circuit breakers, backpressure) are owned by `rules/resilience-engineering.md`; state distribution and consensus by `distributed-systems-patterns`.

## Composite-application pattern map

Each digest below designs a full system by composing the building blocks above — useful as worked examples when your problem resembles one of them.

HLD rows compose the traffic/caching/fan-out blocks; the LLD rows (YouTube LLD, music system, parking lot) are object-modeling companions — lifecycle relationships, SOLID carving, policy-in-data-structure.

| System | Building blocks composed | Digest |
|---|---|---|
| Bit.ly / Pastebin | Estimation, read/write service split, Base62 IDs, metadata/blob separation, expiry purge | [htn-design-bit-ly-and-pastebin.md](references/htn-design-bit-ly-and-pastebin.md) |
| News feed | Push/pull/hybrid fan-out, bounded sorted-set feeds, ID-then-hydrate, cursor pagination | [htn-design-a-news-feed-system.md](references/htn-design-a-news-feed-system.md) |
| Chat system | WebSockets, store-and-forward, staged acks, presence TTL, group fan-out cap | [htn-design-a-chat-system.md](references/htn-design-a-chat-system.md) |
| YouTube (HLD) | Presigned upload, DAG/GoP-parallel transcoding, HLS + client-side ABR, LFU metadata cache | [htn-design-youtube-hld.md](references/htn-design-youtube-hld.md) |
| YouTube (LLD) | Composition/aggregation taxonomy, composite comment trees, observer + factory, SOLID checklist | [htn-design-youtube-lld.md](references/htn-design-youtube-lld.md) |
| Spotify | Estimation forcing a CDN, chunked HLS + DRM, event-log fan-out, polyglot persistence | [htn-design-spotify.md](references/htn-design-spotify.md) |
| Instagram | 1000:1 read dominance, hybrid feed fan-out, ID-then-hydrate, notification coalescing | [htn-design-instagram.md](references/htn-design-instagram.md) |
| Tinder | Geo-indexed proximity search, Bloom-filter seen-exclusion, cheap-cuts-first funnel, atomic mutual-intent match | [htn-design-tinder.md](references/htn-design-tinder.md) |
| Reddit | Vote-dominated write framing, debounced score recompute, per-sort-mode ranked sets, adjacency-list comments | [htn-design-reddit.md](references/htn-design-reddit.md) |
| Twitter | Write buffering, hybrid fan-out + chronological failover, L1/L2/L3 hot-key caching, sliding-window trending | [htn-design-twitter.md](references/htn-design-twitter.md) |
| Amazon | Consistency tiering, two-phase inventory reservation, saga + idempotency keys, queue-leveled flash sales | [htn-design-amazon.md](references/htn-design-amazon.md) |
| Netflix | GOP-parallel encoding, push CDN + proactive warming, signed manifests + DRM split, mixed consistency budget | [htn-design-netflix.md](references/htn-design-netflix.md) |
| Netflix recommendations | Two-stage candidate/ranker funnel, precompute-and-serve, batch + speed layers, diversity injection | [htn-netflix-recommendation-system-machine-learning-system-design.md](references/htn-netflix-recommendation-system-machine-learning-system-design.md) |
| Airbnb | Calendar-table inventory, pessimistic row locks, expiring holds, bitmap fast path, layered search funnel | [htn-design-airbnb.md](references/htn-design-airbnb.md) |
| Music system (LLD) | Aggregation vs composition lifecycles, canonical store + reference sharing, SRP class carving | [htn-design-a-basic-music-system.md](references/htn-design-a-basic-music-system.md) |
| Parking lot (LLD) | Type-indexed availability queues, allocation policy in the comparator, thin entities | [htn-design-a-parking-lot.md](references/htn-design-a-parking-lot.md) |

## Anti-patterns

1. **Designing before estimating.** Without the order of magnitude and the read/write ratio, every architecture choice is a guess — and the wrong workload shape silently invalidates the whole design.
2. **Sharding first.** Sharding is the *last* read-scaling step, after cache and replicas, reserved for when write volume is the bottleneck.
3. **Truncated-hash short keys.** First-N-characters-of-a-hash invites prefix collisions and retry loops; Base62 of a monotonic ID is collision-free by construction.
4. **Per-node rate-limit counters.** Each server sees a fraction of a user's traffic, so the effective limit is silently multiplied by the fleet size. Centralize the counter.
5. **Letting exception defaults choose fail-open vs fail-closed.** Encode the store-outage policy deliberately — and invert it for auth/OTP endpoints.
6. **Proxying binary payloads through the gateway or app tier.** Media goes client → pre-signed URL → object storage → CDN; the API tier touches only metadata. Control plane through the gateway, data plane around it.
7. **Uniform fan-out on write.** One celebrity post becomes a hundred million cache writes; hybrid on a follower/community-size threshold is the production answer.
8. **Computing counts by aggregation at read time.** Denormalize the counter, maintain it asynchronously, keep the interaction table as the source of truth.
9. **Caching per-user or per-second data at a shared edge.** Cross-user leakage is a privacy incident; instantly stale data is worse than no cache.
10. **Mutating a read-hot structure in place.** A live trie (or any structure with millions of readers) is rebuilt offline and snapshot-swapped, never written on the hot path.
11. **Holding a lock across a human-scale wait.** Reserve with an expiring hold, release the lock in milliseconds, confirm after the slow step completes.
12. **Skipping the durable write before delivery.** Store-and-forward is the invariant; an optimistic push that races persistence loses messages.
13. **Unbounded per-entity hot structures.** Any in-memory collection fed by other users' actions (pending likes, feeds, presence sets) needs an explicit cap and a named rebuild source, or your memory profile is hostage to your most popular entity.
14. **Splitting services along tables, size, or repo boundaries.** The only valid boundary is a business capability passing the four-criteria test; anything else is a distributed monolith on layaway.
15. **One database serving every role.** A single store forced to be the relational truth, the feed cache, the search index, and the analytics sink does all of them badly; pick each store from its query shape (and pay the operational cost knowingly).

## References

Digests synthesized from public X threads by Harshit Khosla ([@Harry_The_Nerd](https://x.com/Harry_The_Nerd)) — own-words summaries, no verbatim text.

- [htn-design-bit-ly-and-pastebin.md](references/htn-design-bit-ly-and-pastebin.md) — rounded-constant estimation, Base62 keys, read/write service split, metadata/blob separation, dual-store expiry purge
- [htn-design-a-rate-limiter.md](references/htn-design-a-rate-limiter.md) — the 429/Retry-After contract, four window algorithms, centralized counters, fail-open vs fail-closed
- [htn-design-a-load-balancer.md](references/htn-design-a-load-balancer.md) — L4/L7 split, five algorithms, dual health checks, VIP entry point, TLS termination
- [htn-design-a-content-delivery-network.md](references/htn-design-a-content-delivery-network.md) — cacheability rule, GeoDNS, origin shield, TTL/purge/versioning, Cache-Control vocabulary
- [htn-design-a-notification-system.md](references/htn-design-a-notification-system.md) — channel services, preference-aware router, queue buffering, retry + channel fallback, OTP bypass lane
- [htn-design-a-news-feed-system.md](references/htn-design-a-news-feed-system.md) — push/pull/hybrid fan-out, sorted-set feeds, bounded retention, cursor pagination
- [htn-design-autocomplete-for-search-engines.md](references/htn-design-autocomplete-for-search-engines.md) — trie + precomputed top-N, offline rebuild + snapshot swap, traffic-weighted sharding
- [htn-design-a-unique-id-generator-in-distributed-systems.md](references/htn-design-a-unique-id-generator-in-distributed-systems.md) — five-axis rubric, Snowflake bit layout, scheme decision matrix
- [htn-design-a-chat-system.md](references/htn-design-a-chat-system.md) — WebSocket sizing math, store-and-forward, staged acks, heartbeat/TTL presence, group cap
- [htn-design-youtube-hld.md](references/htn-design-youtube-hld.md) — presigned upload, DAG/GoP transcoding, HLS manifests, client-side ABR, LFU eviction
- [htn-design-youtube-lld.md](references/htn-design-youtube-lld.md) — relationship taxonomy, composite comment trees, observer/factory patterns, SOLID checklist
- [htn-design-spotify.md](references/htn-design-spotify.md) — estimation as a CDN forcing function, chunked HLS + DRM, event-log fan-out, polyglot persistence
- [htn-design-instagram.md](references/htn-design-instagram.md) — 1000:1 read dominance, hybrid fan-out, ID-then-hydrate latency math, coalesced notifications
- [htn-design-tinder.md](references/htn-design-tinder.md) — geo proximity search, Bloom-filter exclusion, funnel-ordered discovery, atomic mutual-intent detection
- [htn-design-reddit.md](references/htn-design-reddit.md) — vote-write dominance, debounced recomputation, per-sort-mode ranked sets, adjacency-list comment trees
- [htn-design-twitter.md](references/htn-design-twitter.md) — 3:1 read/write framing, write buffering, three-tier hot-key caching, sliding-window trending
- [htn-design-amazon.md](references/htn-design-amazon.md) — consistency tiering, two-phase reservation, choreographed saga, queue-leveled flash sales
- [htn-design-netflix.md](references/htn-design-netflix.md) — GOP-parallel encoding, push CDN + cache warming, signed manifests + DRM key split, mixed consistency
- [htn-netflix-recommendation-system-machine-learning-system-design.md](references/htn-netflix-recommendation-system-machine-learning-system-design.md) — candidate/ranker funnel, precompute-and-serve, batch + speed freshness, diversity injection
- [htn-design-airbnb.md](references/htn-design-airbnb.md) — calendar-table inventory, pessimistic locks, expiring holds, bitmap fast path, layered search
- [htn-mental-model-for-microservices.md](references/htn-mental-model-for-microservices.md) — four-criteria test, benefit triad vs cost ledger, Conway's Law
- [htn-design-a-basic-music-system.md](references/htn-design-a-basic-music-system.md) — aggregation lifecycles, canonical store + reference sharing, complexity accounting
- [htn-design-a-parking-lot.md](references/htn-design-a-parking-lot.md) — type-indexed availability, policy-in-comparator ordering, thin entities
- [htn-security-scaling-performance-concurrency-parallelism.md](references/htn-security-scaling-performance-concurrency-parallelism.md) — vertical-then-horizontal posture, database-first bottleneck levers, statelessness prerequisite
- `distributed-systems-patterns` — state distribution, replication, and consensus underneath these building blocks
- `redis-caching-patterns` — cache implementation conventions: namespacing, TTLs, invalidation, stampede protection
- `kafka-config-driven` — the event-log/consumer-group machinery behind the queue-buffered fan-out patterns
- `notifications-and-messaging` — delivery mechanics for the notification fan-out architecture
- `load-testing` — validating the back-of-envelope numbers against reality before launch
- `rules/resilience-engineering.md` (always loaded) — retries, circuit breakers, backpressure, CAP, and clocks; referenced, never restated here
