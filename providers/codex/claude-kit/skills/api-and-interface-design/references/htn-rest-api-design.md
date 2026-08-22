# Digest: Rest API Design

- **Source:** https://x.com/Harry_The_Nerd/status/2054882198604628305
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Backend Engineering
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Fielding's six REST constraints

The article grounds "RESTful" in the six architectural constraints from Roy Fielding's 2000 formulation rather than treating REST as just "JSON over HTTP":

- **Client-server separation** — UI concerns live on the client, data and business logic on the server; each side stays ignorant of the other's internals.
- **Uniform interface** — one standardized interaction contract across all components, which is what lets arbitrary clients consume the API without bespoke knowledge.
- **Layered system** — intermediaries (load balancers, caches, proxies) can be inserted between client and origin; each layer sees only its immediate neighbor, aiding both security and horizontal scale.
- **Cacheability** — every response must state explicitly whether caching it is allowed; done well, this cuts origin load and improves perceived latency.
- **Statelessness** — flagged by the author as the constraint that matters most. The server keeps no per-client session memory; each request carries everything needed to process it (auth token, identity, context). This is the property that makes horizontal scaling trivial.
- **Code on demand (optional)** — the server may ship executable code (e.g., JavaScript) to extend the client; rarely relevant to day-to-day API design.

When to use: as a checklist when judging whether an API design will scale and compose with standard web infrastructure. Trade-off: statelessness pushes context-carrying cost onto every request, in exchange for the ability to add servers freely.

### URL and route structure conventions

Design routes before writing handler code; a good path should be readable almost like natural language. The anatomy the author recommends (illustrated with `https://api.example.com/v1/users`):

- TLS-only scheme.
- A dedicated `api.` subdomain, isolating the API from the main web property.
- A version segment (`v1`) present **from the first release**, so breaking changes ship as `v2` without disturbing existing consumers.
- Resource names as **plural nouns**, even for single-item routes — `/users/123` is a member of the users collection, so `/user/123` is wrong.
- Lowercase paths with hyphens as word separators (not underscores, not camelCase).
- Nesting to express real ownership (`/organizations/42/projects` = projects owned by org 42), capped at roughly two or three levels because deeper hierarchies become unmanageable.

Trade-off: nesting communicates relationships but couples routes to the ownership model; keep it shallow.

### HTTP method choice as idempotency signaling

Method selection communicates intent, and the organizing concept is idempotency — an operation whose repeated execution leaves the server in the same state as a single execution:

| Method | Role | Idempotent |
|---|---|---|
| GET | read | yes |
| POST | create | **no** |
| PUT | full replacement | yes |
| PATCH | partial field update | yes |
| DELETE | removal | yes |

Because POST is the lone non-idempotent verb, retrying an identical POST N times yields N distinct records — which is exactly why payment systems layer **idempotency keys** on top, to keep accidental retries from double-charging.

On PATCH vs PUT: PATCH is for touching a field or two (e.g., updating an email address); PUT is for submitting a complete replacement document. The author observes PATCH dominates in modern APIs.

### Verb-suffixed action endpoints for non-CRUD operations

Some operations don't reduce to create/read/update/delete — cloning a project, or archiving an organization when archiving fans out into background work (member notifications, billing cleanup, data locking). The convention: identify the resource first, then append the action verb as the final path segment, always invoked via POST — e.g. `POST /projects/123/clone`, `POST /organizations/5/archive`, `POST /invoices/88/send`. This keeps intent legible while staying inside REST's grammar. Use it when an "update" would really be a state transition with side effects.

### The list-endpoint triad: pagination, sorting, filtering

An unguarded collection GET works fine until the table holds 500,000 rows and a client asks for all of them. Production list endpoints need three capabilities together:

- **Pagination** — never return an unbounded result set. Ship page metadata next to the rows (e.g., a body with `data`, `total`, `page`, `totalPages`); the total count is what lets a frontend render "page X of Y" affordances.
- **Sorting** — expose order control via query params (a sort field plus a direction param), with a sane server default such as newest-first on creation time.
- **Filtering** — let clients narrow by field equality via query params instead of downloading everything and filtering locally.

Composed, one endpoint handles queries like a filtered, sorted, paginated order list in a single request. Trade-off: more query-parsing surface on the server, in exchange for endpoints that survive data growth.

### Status-code discipline

Status codes are contract, not decoration — misuse forces clients to sniff response bodies to detect failure. The mapping the article prescribes:

- **200** — generic success for reads, updates, and custom actions.
- **201** — specifically when a POST has materialized a new resource.
- **204** — successful DELETE; nothing to return.
- **400** — malformed/invalid client input.
- **401** — missing or invalid authentication.
- **403** — authenticated but not permitted.
- **404** — the addressed resource ID does not exist.
- **409** — request collides with existing state (e.g., duplicate-email signup).
- **422** — syntactically fine but fails validation rules.
- **500** — server-side failure.

Explicit corner case: a list query whose filters match nothing must return **200 with an empty array**, never 404 — an empty set is a valid answer, not an error.

### Consumer-first API design heuristics ("golden rules")

Five working heuristics for API authors:

1. **Derive the data model from the UI** — read the product mockups; the nouns users interact with become resources, the interactions become methods.
2. **Sane defaults everywhere** — assume callers will omit parameters. Default page size to 10, sort to newest-first, new-record status to active; degrade gracefully instead of erroring.
3. **Ruthless naming consistency** — one JSON key convention (the author mandates camelCase) applied uniformly; a field must carry the same name in every endpoint, or every consumer ends up writing defensive translation code.
4. **Interactive documentation** — static docs rot; OpenAPI/Swagger-style tooling produces living docs where consumers fire real test calls from the browser. Docs are a first-class deliverable.
5. **Shape endpoints for the consumer, not the schema** — the API is a product; expose data the way clients need it, and never leak raw table structure, which is an implementation detail.

## Not absorbed

- **Series framing** ("Backend Engineering #4" header) — content-series branding, no technical payload.
- **"Where REST Came From" historical narrative** (1990s web strain, Fielding's 2000 dissertation, the resource/state/transfer etymology walkthrough) — background storytelling; the actionable substance is entirely in the six-constraints section, which is absorbed above.
- **The "tired engineer at 2am (me)" aside** — personal anecdote used to motivate the defaults rule; the rule itself is absorbed.
- **Opening and closing pleasantries** ("I hope this article helped…", "That's all folks, Cheers!") — sign-off, not engineering.
- **Engagement metrics in the capture** (timestamp, view/reply/like counts) — platform chrome, not article content.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; `postCount: 1` in the JSON, no `---AUTHOR-POST-BREAK---` separators present).

**Article outline as authored:**

1. Introduction (why REST APIs are ubiquitous yet easy to design badly)
2. Where REST Came From
3. The Six Constraints That Make an API Truly RESTful
4. Designing Clean, Readable URLs
5. HTTP Methods and the Concept of Idempotency
6. When Standard CRUD Isn't Enough
7. Building List Endpoints That Don't Break Under Load
8. Using Status Codes Correctly
9. Golden Rules for API Engineers
10. Closing sign-off

**Pattern-to-section citations:**

| Digest pattern | Source section |
|---|---|
| Fielding's six REST constraints | "The Six Constraints That Make an API Truly RESTful" (section 3) |
| URL and route structure conventions | "Designing Clean, Readable URLs" (section 4) |
| HTTP method choice as idempotency signaling | "HTTP Methods and the Concept of Idempotency" (section 5) |
| Verb-suffixed action endpoints for non-CRUD operations | "When Standard CRUD Isn't Enough" (section 6) |
| The list-endpoint triad | "Building List Endpoints That Don't Break Under Load" (section 7) |
| Status-code discipline | "Using Status Codes Correctly" (section 8) |
| Consumer-first API design heuristics | "Golden Rules for API Engineers" (section 9) |
