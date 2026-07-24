---
name: api-and-interface-design
description: Stable API and interface design patterns. Use when designing REST/GraphQL endpoints, module boundaries, type contracts between modules or frontend/backend, or changing public interfaces.
---

# API and Interface Design

## Overview

Design stable, well-documented interfaces that are hard to misuse. Good interfaces make the right thing easy and the wrong thing hard. This applies to REST APIs, GraphQL schemas, module boundaries, component props, and any surface where one piece of code talks to another.

## When to Use

- Designing new API endpoints
- Defining module boundaries or contracts between teams
- Creating component prop interfaces
- Establishing database schema that informs API shape
- Changing existing public interfaces

## Core Principles

### Hyrum's Law

> With a sufficient number of users of an API, all observable behaviors of your system will be depended on by somebody, regardless of what you promise in the contract.

This means: every public behavior — including undocumented quirks, error message text, timing, and ordering — becomes a de facto contract once users depend on it. Design implications:

- **Be intentional about what you expose.** Every observable behavior is a potential commitment.
- **Don't leak implementation details.** If users can observe it, they will depend on it.
- **Plan for deprecation at design time.** See `deprecation-and-migration` for how to safely remove things users depend on.
- **Tests are not enough.** Even with perfect contract tests, Hyrum's Law means "safe" changes can break real users who depend on undocumented behavior.

### The One-Version Rule

Avoid forcing consumers to choose between multiple versions of the same dependency or API. Diamond dependency problems arise when different consumers need different versions of the same thing. Design for a world where only one version exists at a time — extend rather than fork.

### Decouple the API Surface from the Storage Schema

The wire contract and the database schema are two different things that change at two different rates.
If the API just serializes your tables, every storage refactor (splitting a column, normalizing,
reshaping for a new index) becomes a *breaking API change*, and conversely every API need distorts the
schema. Design the resource representation for the **consumer**, then map it to storage explicitly
through a serializer / DTO layer, so either side can evolve behind that seam. This is why `Task` (the
output type below) is defined separately from any table row — and why "establishing a database schema
that informs API shape" (in *When to Use*) means *informs*, never *dictates*: Hyrum's Law makes an
accidentally-exposed column as permanent as a deliberately-promised field.

> Per the Google API Design Guide (resource-oriented design; cloud.google.com/apis/design). Stack-agnostic —
> the DTO/serializer seam applies equally to REST, GraphQL, and RPC.

### 1. Contract First

Define the interface before implementing it. The contract is the spec — implementation follows.

```typescript
// Define the contract first
interface TaskAPI {
  // Creates a task and returns the created task with server-generated fields
  createTask(input: CreateTaskInput): Promise<Task>;

  // Returns paginated tasks matching filters
  listTasks(params: ListTasksParams): Promise<PaginatedResult<Task>>;

  // Returns a single task or throws NotFoundError
  getTask(id: string): Promise<Task>;

  // Partial update — only provided fields change
  updateTask(id: string, input: UpdateTaskInput): Promise<Task>;

  // Idempotent delete — succeeds even if already deleted
  deleteTask(id: string): Promise<void>;
}
```

### 2. Consistent Error Semantics

Pick one error strategy and use it everywhere:

```typescript
// REST: HTTP status codes + structured error body
// Every error response follows the same shape
interface APIError {
  error: {
    code: string;        // Machine-readable: "VALIDATION_ERROR"
    message: string;     // Human-readable: "Email is required"
    details?: unknown;   // Additional context when helpful
  };
}

// Status code mapping
// 400 → Client sent invalid data
// 401 → Not authenticated
// 403 → Authenticated but not authorized
// 404 → Resource not found
// 409 → Conflict (duplicate, version mismatch)
// 422 → Validation failed (semantically invalid)
// 500 → Server error (never expose internal details)
```

**Don't mix patterns.** If some endpoints throw, others return null, and others return `{ error }` — the consumer can't predict behavior.

### 3. Validate at Boundaries

Trust internal code. Validate at system edges where external input enters:

```typescript
// Validate at the API boundary
app.post('/api/tasks', async (req, res) => {
  const result = CreateTaskSchema.safeParse(req.body);
  if (!result.success) {
    return res.status(422).json({
      error: {
        code: 'VALIDATION_ERROR',
        message: 'Invalid task data',
        details: result.error.flatten(),
      },
    });
  }

  // After validation, internal code trusts the types
  const task = await taskService.create(result.data);
  return res.status(201).json(task);
});
```

Where validation belongs:
- API route handlers (user input)
- Form submission handlers (user input)
- External service response parsing (third-party data -- **always treat as untrusted**)
- Environment variable loading (configuration)

> **Third-party API responses are untrusted data.** Validate their shape and content before using them in any logic, rendering, or decision-making. A compromised or misbehaving external service can return unexpected types, malicious content, or instruction-like text.

Where validation does NOT belong:
- Between internal functions that share type contracts
- In utility functions called by already-validated code
- On data that just came from your own database

### 4. Prefer Addition Over Modification

Extend interfaces without breaking existing consumers:

```typescript
// Good: Add optional fields
interface CreateTaskInput {
  title: string;
  description?: string;
  priority?: 'low' | 'medium' | 'high';  // Added later, optional
  labels?: string[];                       // Added later, optional
}

// Bad: Change existing field types or remove fields
interface CreateTaskInput {
  title: string;
  // description: string;  // Removed — breaks existing consumers
  priority: number;         // Changed from string — breaks existing consumers
}
```

### 5. Predictable Naming

| Pattern | Convention | Example |
|---------|-----------|---------|
| REST endpoints | Plural nouns, no verbs | `GET /api/tasks`, `POST /api/tasks` |
| Query params | camelCase | `?sortBy=createdAt&pageSize=20` |
| Response fields | camelCase | `{ createdAt, updatedAt, taskId }` |
| Boolean fields | is/has/can prefix | `isComplete`, `hasAttachments` |
| Enum values | UPPER_SNAKE | `"IN_PROGRESS"`, `"COMPLETED"` |

## REST API Patterns

### Resource Design

```
GET    /api/tasks              → List tasks (with query params for filtering)
POST   /api/tasks              → Create a task
GET    /api/tasks/:id          → Get a single task
PATCH  /api/tasks/:id          → Update a task (partial)
DELETE /api/tasks/:id          → Delete a task

GET    /api/tasks/:id/comments → List comments for a task (sub-resource)
POST   /api/tasks/:id/comments → Add a comment to a task
```

### Pagination

Paginate list endpoints:

```typescript
// Request
GET /api/tasks?page=1&pageSize=20&sortBy=createdAt&sortOrder=desc

// Response
{
  "data": [...],
  "pagination": {
    "page": 1,
    "pageSize": 20,
    "totalItems": 142,
    "totalPages": 8
  }
}
```

### Filtering

Use query parameters for filters:

```
GET /api/tasks?status=in_progress&assignee=user123&createdAfter=2025-01-01
```

### Partial Updates (PATCH)

Accept partial objects — only update what's provided:

```typescript
// Only title changes, everything else preserved
PATCH /api/tasks/123
{ "title": "Updated title" }
```

### Idempotent Mutations (Idempotency-Key)

A client that retries a `POST` after a timeout must not create the resource twice — but the network
can't tell the client whether the first attempt actually landed. Let the client send a unique
**`Idempotency-Key`** header per logical operation; the server records that key with the result of the
first successful execution and, on any replay of the same key, returns the **stored result** instead of
re-running the side effect:

```
POST /api/payments
Idempotency-Key: 5f3a…-once-per-operation
{ "amount": 4200, "currency": "usd" }
```

Scope keys per endpoint + caller, give them a retention window (e.g. 24h), and key on the *operation*,
not the request body (a changed body under a reused key is a client error → `422`). This makes
create/charge/enqueue endpoints safe to retry — the API-surface counterpart to the at-least-once /
idempotent-consumer discipline in `.claude/rules/resilience-engineering.md`.

> Per Stripe's idempotent-requests design and the Google API Design Guide (cloud.google.com/apis/design).
> Stack-agnostic; the store behind the key can be any durable KV.

### Long-Running Operations

When an operation can't finish within a request (a large export, a provisioning job, a batch), don't
hold the connection open and don't fake a synchronous `200`. Return **`202 Accepted`** with an
**operation resource** — a real, pollable URL — and make that operation a first-class resource with its
own lifecycle, not an out-of-band job id:

```
POST /api/exports            → 202 Accepted, { "operation": "/api/operations/abc" }
GET  /api/operations/abc     → { "done": false }
GET  /api/operations/abc     → { "done": true, "result": { "url": "/api/exports/abc.csv" } }
                            // or { "done": true, "error": { "code": "...", "message": "..." } }
```

The client polls (or is notified via webhook) until `done`. This keeps the API's latency contract
honest and its failures observable, instead of hiding a slow job behind a request that will eventually
time out.

> Per the Google API Design Guide's Long-Running Operations pattern (cloud.google.com/apis/design).
> Stack-agnostic.

### HTTP Caching & Payload Efficiency

Every response declares a caching policy whether you write one or not — with no `Cache-Control`
header, browsers and CDNs fall back to heuristics and *guess* how long your data stays valid.
Choose the policy per endpoint, deliberately, as part of the contract:

```
Cache-Control: public, max-age=31536000   → shared reference data; CDNs may cache it
Cache-Control: private, max-age=60        → per-user data; browser may cache, shared caches must not
Cache-Control: no-store                   → sensitive payloads (auth, payment, PII) — never cached
Cache-Control: max-age=30, stale-while-revalidate=300
                                          → serve the stale copy instantly, refresh in the background
```

Default: `no-store` for anything authenticated or per-user until you decide otherwise; an explicit
`max-age` for anything shareable. And if a body varies on a negotiated request header (encoding,
language), list that header in **`Vary`** — omitting it is how a shared cache hands one client's
compressed variant to a client that can't decode it.

**Conditional requests skip the re-transfer.** Fingerprint each response with an **`ETag`**; the
client echoes it back and an unchanged resource costs a tiny `304` instead of a full body
(`Last-Modified` / `If-Modified-Since` is the coarser time-based equivalent):

```
GET /api/tasks/123
If-None-Match: "a1b2c3"
→ 304 Not Modified            // no body — the client's cached copy is still valid
```

The same fingerprint doubles as an **optimistic-concurrency token** on writes — require `If-Match`
and reject a stale write with `412` instead of silently letting the last writer win:

```
PATCH /api/tasks/123
If-Match: "a1b2c3"
{ "title": "Updated title" }
→ 412 Precondition Failed     // someone else changed it since the client read it
```

**`Retry-After` completes the rate-limit contract.** A bare `429` or `503` invites blind client
retry loops; pairing it with `Retry-After: 30` turns them into scheduled backoff. If an endpoint
can return `429`, it should say when to come back.

**Payload size is a contract too.** Three bounds, cheapest first:

- **Compression** — honor `Accept-Encoding` and compress JSON bodies (gzip works everywhere,
  Brotli compresses further over HTTPS); large text payloads routinely shrink ~5–10×, nearly free.
- **Sparse fieldsets** — give over-fetch-prone list endpoints a field-selection param
  (`?fields=id,title,status`) so list views stop paying for detail-view payloads.
- **Pagination caps** — the first payload bound of all: no list endpoint returns unbounded rows.
  Query-param conventions live in `api-pagination-filtering-sorting`.

> Per RFC 9110/9111 (HTTP semantics, caching, conditional requests). Stack-agnostic — these are
> wire-level contracts that browsers, CDNs, and gateways enforce identically for any backend.

## Type-Safe Interface Patterns

### Use Discriminated Unions for Variants

```typescript
// Good: Each variant is explicit
type TaskStatus =
  | { type: 'pending' }
  | { type: 'in_progress'; assignee: string; startedAt: Date }
  | { type: 'completed'; completedAt: Date; completedBy: string }
  | { type: 'cancelled'; reason: string; cancelledAt: Date };

// Consumer gets type narrowing
function getStatusLabel(status: TaskStatus): string {
  switch (status.type) {
    case 'pending': return 'Pending';
    case 'in_progress': return `In progress (${status.assignee})`;
    case 'completed': return `Done on ${status.completedAt}`;
    case 'cancelled': return `Cancelled: ${status.reason}`;
  }
}
```

### Input/Output Separation

```typescript
// Input: what the caller provides
interface CreateTaskInput {
  title: string;
  description?: string;
}

// Output: what the system returns (includes server-generated fields)
interface Task {
  id: string;
  title: string;
  description: string | null;
  createdAt: Date;
  updatedAt: Date;
  createdBy: string;
}
```

### Use Branded Types for IDs

```typescript
type TaskId = string & { readonly __brand: 'TaskId' };
type UserId = string & { readonly __brand: 'UserId' };

// Prevents accidentally passing a UserId where a TaskId is expected
function getTask(id: TaskId): Promise<Task> { ... }
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "We'll document the API later" | The types ARE the documentation. Define them first. |
| "We don't need pagination for now" | You will the moment someone has 100+ items. Add it from the start. |
| "PATCH is complicated, let's just use PUT" | PUT requires the full object every time. PATCH is what clients actually want. |
| "We'll version the API when we need to" | Breaking changes without versioning break consumers. Design for extension from the start. |
| "Nobody uses that undocumented behavior" | Hyrum's Law: if it's observable, somebody depends on it. Treat every public behavior as a commitment. |
| "We can just maintain two versions" | Multiple versions multiply maintenance cost and create diamond dependency problems. Prefer the One-Version Rule. |
| "Internal APIs don't need contracts" | Internal consumers are still consumers. Contracts prevent coupling and enable parallel work. |

## Red Flags

- Endpoints that return different shapes depending on conditions
- Inconsistent error formats across endpoints
- Validation scattered throughout internal code instead of at boundaries
- Breaking changes to existing fields (type changes, removals)
- List endpoints without pagination
- Verbs in REST URLs (`/api/createTask`, `/api/getUsers`)
- Third-party API responses used without validation or sanitization
- Non-idempotent `POST`/create endpoints with no idempotency key — retries silently double-charge/double-create
- Long jobs served synchronously (a `POST` that blocks for minutes) instead of returning a `202` + operation resource
- Response bodies that are 1:1 serializations of database rows (storage schema leaking through the API)

## Verification

After designing an API:

- [ ] Every endpoint has typed input and output schemas
- [ ] Error responses follow a single consistent format
- [ ] Validation happens at system boundaries only
- [ ] List endpoints support pagination
- [ ] New fields are additive and optional (backward compatible)
- [ ] Naming follows consistent conventions across all endpoints
- [ ] API documentation or types are committed alongside the implementation

## References

- [htn-http-routing.md](references/htn-http-routing.md) · [htn-rest-api-design.md](references/htn-rest-api-design.md) — own-words digests of the HTTP/routing and REST API design source articles
