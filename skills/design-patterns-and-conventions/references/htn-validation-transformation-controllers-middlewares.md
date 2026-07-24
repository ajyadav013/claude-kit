# Digest: Validation, Transformation, Controllers, Middlewares

- **Source:** https://x.com/Harry_The_Nerd/status/2053882356071911853
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Backend Engineering (article #3 in the author's series)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

## Patterns

### Two-layer validation (schema vs. business)

Split input checking into two distinct tiers. The first tier is schema validation: purely
structural checks (types, ranges, format of an email string) performed declaratively at the
edge with tools such as Zod, Joi, Pydantic, or Jakarta Bean Validation. The second tier is
business validation: checks that need application context or a database round-trip (uniqueness
of a username, whether an account holds enough funds), which live in the service layer.

- **When to use:** every endpoint that accepts client input.
- **Trade-offs / pitfalls:** the classic failure mode is blending the tiers — a DB query hiding
  inside a schema validator, or domain rules scattered through controllers. Keep the schema tier
  stateless and cheap; treat the business tier as first-class domain logic.
- **Error-reporting discipline:** reject bad input immediately with specific messages. A bare
  400 with no detail forces guesswork on the client. Accumulate every violation rather than
  stopping at the first, and emit them in one consistent error shape.

### Explicit transformation via DTOs at both edges

Data arriving from clients and data leaving for clients rarely match the internal shape, so
convert deliberately at the boundaries. Inbound examples: whitespace trimming, lowercasing
emails, parsing date strings into date objects, splitting comma-delimited values into arrays.
Outbound examples: removing sensitive internals (e.g., a stored password hash), converting
snake_case column names to camelCase JSON keys, collapsing nested rows into flat DTOs, and
emitting timestamps as ISO 8601.

- **Key idea:** a transformation should never happen by accident. Returning a DB entity
  straight to the client is an implicit transform that leaks internals. Declare dedicated
  input and output DTO types; tools like class-transformer (NestJS) or DRF serializers make
  this a formal step.
- **Canonical flow:** incoming request → validated/converted input DTO → domain object →
  output DTO → serialized response.

### Thin controllers (HTTP-only orchestration)

The controller's remit is deliberately small: accept the request, hand off to a service, shape
the HTTP reply. No business decisions, no repository access, no interpretation of what the data
means. It also owns HTTP-specific mechanics — status codes, headers, content negotiation —
precisely so services stay transport-agnostic and can be invoked from a CLI or a job queue
unchanged.

- **Smell:** a controller that imports repositories, branches on domain conditions, or wires
  several services together directly. Such controllers are hard to test and break single
  responsibility.

### Service layer as the home of business logic

Services encode what the system actually does — order placement, refund processing, account
deactivation rules. Their responsibilities: coordinating multiple repository calls, enforcing
invariants, firing side effects (emails, event publication), and owning transaction boundaries.

- **Statelessness rule:** never park request-scoped data on a service instance. Services are
  usually singletons, so per-request fields on them are latent concurrency bugs.
- **Testability payoff:** because dependencies arrive by injection and nothing HTTP-specific
  leaks in, services unit-test quickly and in isolation.

### Repository abstraction over persistence

Repositories present a domain-centric interface (find by id, find by email, save, delete) that
accepts and returns domain objects while concealing whether the backing store is PostgreSQL,
MongoDB, or a file. If services write raw SQL or chain ORM query builders, they are welded to
one database and painful to test or migrate.

- **Boundary rule:** a complex query (e.g., recent signups with no purchases) belongs in the
  repository; the decision about what to do with the result belongs in the service.
- **Granularity trade-off:** avoid both extremes — one all-purpose criteria-driven find method
  (too generic) and one method per UI screen (too specific). Target methods that mirror natural
  domain operations.

### Middleware for cross-cutting pipeline concerns

Middleware wraps the request pipeline around the controller and is the correct home for logic
shared by many routes but owned by none: token/session verification with user attachment,
request logging (method, path, latency, status), rate limiting, CORS headers, unique request-ID
stamping for tracing, and body parsing.

- **Ordering:** composition order must be intentional and explicit — authentication precedes
  authorization; logging typically encloses everything else.
- **Boundary rule:** middleware understands requests and responses, not the domain. Gating a
  resource-level decision (such as an admin check on a specific resource) in middleware is
  authorization logic that belongs in the service or a dedicated guard/policy layer. The
  author's rule of thumb: middleware enriches the pipeline; services act on the enrichment.

### Request context for per-request state propagation

Instead of threading the current user, request ID, tenant, locale, and trace context through
every function signature, attach them to a context object scoped to one request's lifetime.
Auth middleware populates it; downstream services and audit loggers read it via injection.

- **Mechanisms:** AsyncLocalStorage in Node.js (safe across async hops), request-scoped
  providers in NestJS, ThreadLocal in Java/Spring.
- **Scope discipline:** include only identity/tracing-style data. Anything derivable from the
  domain model or computable on demand does not belong; the context is not a dumping ground
  for application state.

### Layered request lifecycle (composition of all the above)

The pieces compose into a predictable pipeline: context data flows vertically through every
layer while transformations sit at the two edges (sanitize inbound, shape outbound), and each
layer has exactly one job. The payoff of the separation is operational: failures have an
obvious place to look, new requirements have an obvious place to land, and tests have an
obvious seam to mock.

## Not absorbed

- Series framing ("Backend Engineering #3") and the intro sentence promising to cover core
  building blocks — table-of-contents scaffolding, no technical content.
- The author's self-deprecating aside about the lifecycle diagram ("I tried :p") and the
  closing sign-off ("That's all, folks") — conversational filler.
- The "(personal)" trick label in the middleware section — the underlying rule is absorbed
  above; the framing as a personal tip is not substance.
- Engagement metadata (timestamp, view/like/repost counts) — platform noise.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; no thread breaks present).
- **Article outline as authored:**
  1. Intro (series header + scope statement)
  2. Validation
  3. Transformations
  4. Controllers
  5. Services
  6. Repositories
  7. Middlewares
  8. Request Context
  9. How It All Fits Together
- **Pattern-to-section citations:**
  - Two-layer validation (schema vs. business) — section "Validation"
  - Explicit transformation via DTOs at both edges — section "Transformations"
  - Thin controllers (HTTP-only orchestration) — section "Controllers"
  - Service layer as the home of business logic — section "Services"
  - Repository abstraction over persistence — section "Repositories"
  - Middleware for cross-cutting pipeline concerns — section "Middlewares"
  - Request context for per-request state propagation — section "Request Context"
  - Layered request lifecycle — section "How It All Fits Together"
- **Capture caveat:** the final section refers to a cleanly layered request lifecycle but the
  capture jumps straight to the context/transformation summary, strongly suggesting an embedded
  diagram image that the text-only render did not capture. Code snippets (thin controller,
  service method, repository interface, context middleware) survived as inline text.
