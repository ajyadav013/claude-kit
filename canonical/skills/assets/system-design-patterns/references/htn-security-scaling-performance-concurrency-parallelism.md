# Digest: Security, Scaling & Performance, Concurrency & Parallelism

- **Source:** https://x.com/Harry_The_Nerd/status/2077722979882963122
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Backend Engineering (series part 7, final)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Authentication / authorization as separate layers
Identity verification (who is calling) and permission checking (what they may do) are distinct
concerns living at different depths: identity is typically resolved in middleware (token/session/API-key
checks, failing with 401), while permission checks belong next to the resource being accessed
(failing with 403). Merging both into a single middleware gate is called out as a recurring mistake —
it couples unrelated logic and makes per-resource checks easy to skip.

### JWT vs server-side sessions
Signed stateless tokens let every instance validate a request without a datastore lookup, which
suits horizontally scaled APIs and mobile clients. The cost is revocation: a token stays valid until
expiry even after logout or a ban. Mitigations are short lifetimes (on the order of 15 minutes)
paired with refresh tokens, or a small denylist kept in Redis. Server-held sessions invert the
trade: instant revocation, but every request needs a lookup and scaled deployments need shared
session storage. Neither wins universally — pick per client model.

### Slow, salted password hashing
Fast digests (MD5, SHA-256) are disqualified for credentials precisely because speed lets an
attacker who steals the table test billions of candidates per second. Purpose-built KDFs —
bcrypt, scrypt, Argon2 (the current recommendation) — are intentionally slow and memory-hungry
and salt automatically so equal passwords hash differently. A work/cost factor of roughly 10–12
is suggested as a sane default.

### Standard web-vulnerability mitigations
A checklist of the classic attack classes and their canonical fixes: injection into SQL is closed
by parameterized/prepared statements (never string-building queries from input); script injection
(XSS) by output sanitization, CSP headers, and avoiding untrusted `innerHTML`; forged cross-site
requests (CSRF) by tokens for cookie/session apps plus SameSite cookies and CORS; and IDOR by
checking that the authenticated caller actually owns the specific object requested, not merely
that they are logged in. Login, password-reset, and OTP endpoints additionally need rate limits,
exponential backoff, and lockout after repeated failures to stop brute forcing.

### Secrets kept out of the codebase
No credentials in source, and not in a committed `.env` either. Inject via runtime environment
variables or a dedicated secrets manager (Vault, AWS/GCP secret services), rotate on a schedule,
audit access, and treat any leak as an immediate compromise requiring rotation.

### Transport security everywhere
TLS on every hop: force HTTP→HTTPS redirects, set HSTS headers, and never carry sensitive data
in the clear. On the outbound side, disabling certificate validation to work around a connection
failure converts a networking bug into a security hole — validate certs on calls to external
services too.

### Vertical then horizontal scaling
Adding CPU/RAM/disk to one box is zero-refactor but hits a hard (and increasingly expensive)
ceiling; adding instances behind a distributor has effectively no ceiling but demands an app
designed for it — no instance-local state, externalized sessions, distributed caching. The
recommended posture: start vertical if you like, but adopt horizontal-friendly habits from day
one because the retrofit is far costlier than the discipline.

### Load balancing over stateless instances
A balancer spreads traffic using round-robin, least-connections, or IP-hash (the last when
session affinity is required). The prerequisite that makes any of these strategies simple is
statelessness — if one instance holds data another doesn't, routing and failure handling both
get painful.

### Database as the first bottleneck
Stateless app tiers scale trivially; the stateful database does not, so it degrades first. The
levers, in the order presented: index the columns you filter/sort on (a right index turns a
million-row scan into a handful, but each extra index taxes writes and storage); kill N+1 query
loops with eager loading/JOINs (fetching 100 users then each user's orders separately is 101
queries where 2 suffice); pool connections rather than opening one per request (PgBouncer or
ORM pool settings); split reads onto replicas while writes hit the primary, staying aware that
replication lag means recently written data may not be replica-visible — route
consistency-critical reads to the primary; and make pagination mandatory (cursor-based is more
efficient, offset-based simpler) with enforced page-size caps.

### Cache-first load absorption
A cache hit skips both query and computation, and under load that difference is framed as the
line between a system that survives and one that collapses. (Detailed mechanics are deferred to
an earlier series installment on caching.)

### Profile before optimizing
Measure, don't guess: language profilers (clinic.js/Node built-in, cProfile/py-spy,
async-profiler/JFR) plus the database's slow-query log locate real hotspots — slow queries,
allocation churn, CPU work stalling an event loop, redundant (de)serialization. The anti-pattern
warned against: spending a week saving 10 ms in an hourly job while a 200 ms query fires on every
request.

### Lean, compressible, cache-friendly API responses
Return only the fields the client needs (field-selection parameters or GraphQL if over-fetching
persists); compress with gzip/Brotli (a 500 KB JSON body shrinking to ~50 KB matters on mobile);
and let clients skip requests entirely via ETags and Cache-Control.

### Concurrency vs parallelism
Concurrency is managing many in-flight tasks (a single-core event loop interleaving work);
parallelism is executing several tasks in the same instant (multiple cores). You can have the
first without the second, and choosing a runtime model means knowing which one you're getting.

### Event-loop model and its CPU-bound blind spot
Node's single-threaded loop achieves concurrency through non-blocking I/O — an outstanding
query registers a callback and yields control, so the loop keeps serving other work. Excellent
for I/O-heavy servers; disastrous for CPU-heavy work, since one long computation stalls every
request. The rule: move CPU-bound work to Worker Threads or a separate process, never onto the
loop.

### Runtime threading models compared
Java maps requests to pooled OS threads — true multi-core parallelism at the price of ~1 MB+
stacks and context-switch cost, with pool sizing a genuine tuning problem (too small queues
requests, too large exhausts memory). Go's runtime-scheduled goroutines are cheap enough to run
in the millions, multiplexed onto OS threads for you. Python's GIL blocks parallel bytecode
execution across threads, so threads help only for I/O concurrency; CPU parallelism requires
`multiprocessing` (separate processes, each with its own GIL).

### Race conditions and their fixes
When two concurrent read-modify-write sequences interleave on shared state, the result depends
on ordering — illustrated by two threads both reading a balance of 100, each subtracting 50,
and both writing 50 where 0 is correct. Remedies: pessimistic DB locks (`SELECT FOR UPDATE`),
optimistic locking (version column checked at write time), or making the whole sequence atomic
inside a transaction. In-process, mutexes serialize access to shared state but should be held
briefly and used sparingly — long-held locks turn concurrency back into a queue.

### Deadlock prevention and recovery
Two transactions each holding a lock the other needs will wait forever. Prevent by acquiring
locks in one global order everywhere, keeping transactions short, and using acquisition timeouts.
Databases typically detect the cycle and abort one victim transaction — application code should
expect that error path and retry.

### Parallelize independent awaits
Async/await reads sequentially, which tempts developers into serializing independent operations.
When steps don't depend on each other, launch them together (`Promise.all`-style) so total
latency approximates the slowest single step instead of the sum; reserve sequential awaiting for
genuinely dependent chains.

### Explicit backpressure
When a producer outpaces its consumer, unbounded queues grow until memory runs out — the
canonical OOM-under-load failure. The fix is signaling upstream: pause readable streams when a
writable buffer fills, cap queue depth and reject or block producers at the cap. This must be
designed in deliberately; it does not emerge by default.

### Cross-cutting coupling of the three areas
The closing synthesis: horizontal scaling forces statelessness, which dictates the session/auth
strategy; heavy concurrent load is what surfaces latent race conditions; caching that offloads
the database must still invalidate safely so stale data never leaks across tenants. The unifying
discipline is building these properties in from the start rather than retrofitting after an
incident.

## Not absorbed

- Series framing ("Backend Engineering #7 (Final Part)", "that's it for the series") — publication
  scaffolding, not engineering content.
- Closing call-to-action asking readers to like, comment, repost, and share — audience-growth
  promotion.
- Engagement metadata trailing the capture (view/reply/repost/like counts, timestamp) — platform
  chrome, not article content.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; `postCount: 1` in the JSON, and no
  `---AUTHOR-POST-BREAK---` separators appear in the text).

**Article outline as the author structured it:**
1. Security (intro)
2. Authentication vs Authorization
3. JWT and Sessions
4. Password Storage
5. Common Vulnerabilities
6. Secrets Management
7. Transport Security
8. Scaling and Performance (intro)
9. Vertical vs Horizontal Scaling
10. Load Balancing
11. Database Performance
12. Caching for Performance
13. Profiling and Identifying Bottlenecks
14. API Design for Performance
15. Concurrency and Parallelism (intro)
16. The Event Loop Model (Node.js)
17. Threading Models (Java, Go, Python)
18. Race Conditions
19. Deadlocks
20. Async/Await and Structured Concurrency
21. Backpressure
22. Putting It Together

**Pattern → source-section mapping:**

| Pattern | Article section |
|---|---|
| Authentication / authorization as separate layers | Authentication vs Authorization (2) |
| JWT vs server-side sessions | JWT and Sessions (3) |
| Slow, salted password hashing | Password Storage (4) |
| Standard web-vulnerability mitigations | Common Vulnerabilities (5) |
| Secrets kept out of the codebase | Secrets Management (6) |
| Transport security everywhere | Transport Security (7) |
| Vertical then horizontal scaling | Vertical vs Horizontal Scaling (9) |
| Load balancing over stateless instances | Load Balancing (10) |
| Database as the first bottleneck | Database Performance (11) |
| Cache-first load absorption | Caching for Performance (12) |
| Profile before optimizing | Profiling and Identifying Bottlenecks (13) |
| Lean, compressible, cache-friendly API responses | API Design for Performance (14) |
| Concurrency vs parallelism | Concurrency and Parallelism intro (15) |
| Event-loop model and its CPU-bound blind spot | The Event Loop Model (16) |
| Runtime threading models compared | Threading Models (17) |
| Race conditions and their fixes | Race Conditions (18) |
| Deadlock prevention and recovery | Deadlocks (19) |
| Parallelize independent awaits | Async/Await and Structured Concurrency (20) |
| Explicit backpressure | Backpressure (21) |
| Cross-cutting coupling of the three areas | Putting It Together (22) |

**Capture caveats:** the Async/Await section references example operations ("those three
operations") whose code block did not survive the text capture — likely an embedded snippet or
image the logged-out render dropped. The Caching section explicitly defers to an earlier series
installment not present in this capture. The "structured concurrency" phrase in section 20's
heading is not elaborated in the body beyond `Promise.all` guidance.
