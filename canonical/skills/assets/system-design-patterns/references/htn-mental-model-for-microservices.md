# Digest: Mental Model for Microservices

- **Source:** http://x.com/Harry_The_Nerd/status/2080261902593065465
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Microservices
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Four-criteria microservice definition
A service only qualifies as a microservice when all four of these hold simultaneously: (1) it can be released on its own, with no cross-service release coordination; (2) it is the sole owner of its data store — nothing else queries its database directly; (3) its boundary corresponds to one business capability (e.g. payments, inventory, notifications) rather than a technical tier; (4) a single team is accountable for it across its whole lifecycle, including operations and on-call. Use this as the acceptance test when carving out or reviewing a service boundary. The trade-off implicit in the definition: each criterion imposes discipline (release automation, data-access contracts, capability mapping, team topology) that a shared-everything codebase avoids.

### Distributed-monolith failure mode
If even one of the four criteria is violated — say, two services sharing a table, or releases that must ship in lockstep — the result is a distributed monolith: monolith-grade coupling plus network-grade failure modes. This is the diagnostic to run before claiming a system "has microservices."

### Anti-pattern debunks (what a microservice is not)
Four commonly conflated properties that are orthogonal to the architecture:
- **Size is irrelevant.** A valid service may be hundreds or tens of thousands of lines; the boundary is the criterion, not line count.
- **Containers are orthogonal.** Docker is a packaging/deployment mechanism; monoliths run fine in containers and microservices run fine on bare metal.
- **Repo layout is orthogonal.** Monorepo vs. many repos is an organizational choice, decoupled from service boundaries.
- **One-service-per-table is the worst split.** Partitioning by database schema yields a distributed database with added network hops. Split along business capabilities, never along tables. Use these debunks when reviewing designs that justify a split with "it's small / it's containerized / it has its own repo."

### The benefit triad
The legitimate payoff, when the definition is met: independent deployment (each team releases on its own cadence, no shared release train), independent scaling (scale only the hot service, not the whole system), and independent ownership (technology and design decisions made inside the boundary without org-wide sign-off). These are the only three benefits worth citing; anything else is usually a restated anti-pattern.

### The cost ledger
Every benefit above is purchased with concrete costs that must be designed for up front:
- **Network latency and unreliability** — in-process calls become remote calls with new failure classes.
- **Partial failure** — one service can be down while others are healthy, so all-or-nothing assumptions break and degradation paths must be explicit.
- **Loss of cross-service transactions** — no shared database means eventual consistency must be reasoned about and designed around.
- **Distributed debugging** — a request may traverse several services, so distributed tracing, correlation IDs, and log aggregation replace the single stack trace.
- **Operational multiplication** — more deployables means more pipelines, monitoring, and infrastructure spend.
Treat this list as the entry price, not a reason to refuse: the decision is whether the triad is worth this ledger for the specific system.

### Conway's Law as a boundary-design input
System structure will mirror the org's communication structure regardless of intent, so service boundaries are as much a people decision as a technical one. Corollary: if three teams must constantly coordinate to ship anything, splitting their code into three services does not remove the coordination — it relocates it into the network layer. Practical use: design team boundaries deliberately first, and the architecture has a chance of following; do not use service extraction as a fix for organizational coupling.

### Adoption heuristic (when microservices fit)
Microservices are a trade-off decision, not a default. Choose them when the cost ledger is justified by the benefit triad for the problem at hand — typically a large organization where multiple teams block each other's deployments. A small team on an early-stage product usually should not pay the price.

## Not absorbed

- **"How to frame this in an interview" delivery advice** — coaching on how to phrase the answer to an interviewer; the underlying trade-off heuristic was absorbed above, the presentation tips were not.
- **Course framing ("Microservices course - Part 1", sign-off teasing future parts)** — series promotion, no engineering content.
- **Engagement call (like/comment/share/repost) and view/reply counts** — platform promotion and metrics, not substance.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; capture JSON reports postCount 1, ~4.9k chars).
- **Article outline as authored:**
  1. Intro — most people cannot define a microservice or its costs
  2. What a microservice actually is
  3. Anti-Patterns in Microservices
  4. The core promise
  5. The core cost
  6. Conway's Law
  7. How to frame this in an interview
  8. Sign-off / engagement call
- **Pattern-to-section citations:**
  - Four-criteria microservice definition — section 2 ("What a microservice actually is")
  - Distributed-monolith failure mode — closing of section 2
  - Anti-pattern debunks — section 3 ("Anti-Patterns in Microservices")
  - The benefit triad — section 4 ("The core promise")
  - The cost ledger — section 5 ("The core cost")
  - Conway's Law as a boundary-design input — section 6 ("Conway's Law")
  - Adoption heuristic — section 7 (the engineering judgment embedded in the interview-framing section)
