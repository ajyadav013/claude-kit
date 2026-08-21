---
paths:
  - "**/*.js"
  - "**/*.cjs"
  - "**/*.mjs"
  - "**/*.ts"
---

# Express backend patterns

Stack-specific conventions for the backend. This overlay is installed into `.claude/rules/` only
when the **Node.js · Express** stack is selected. It complements the generic rules - read
`.claude/rules/code-organization.md`, `.claude/rules/design-patterns.md`, and
`.claude/rules/testing.md` first; this file makes them concrete for Express.

## Stack

- **Node.js 20+**, **Express 4/5**, and **TypeScript** when the project is typed.
- Tests: the project's own runner, commonly **Jest**, **Vitest**, or **Mocha** with **supertest**
  for HTTP coverage.
- Tooling: the repository's own **lint**, **typecheck**, and **build** commands are the source of
  truth. Use the stack's configured package manager and scripts rather than ad hoc shell commands.

Run the project's own commands for these tasks (see the **Commands** section of `CLAUDE.md`):
install, dev, test, lint, typecheck, build.

## Layered architecture (never skip a layer)

```
route/controller (src/routes/, src/controllers/)  HTTP only: validate request, call service, map errors -> status
  -> service (src/services/)                      business logic; no Express imports
    -> repository/data access (src/repositories/) queries and persistence only
      -> model/schema (src/models/, src/schemas/) plain data definitions
middleware (src/middleware/)                      cross-cutting concerns: auth, logging, parsing
```

Rules of thumb:
- **Routes stay thin.** No database queries and no business rules. Parse input, call the service,
  translate domain errors to HTTP responses.
- **Services never import Express.** They return values or throw domain errors; the route decides
  the status code and response shape.
- **Keep request-specific work in middleware.** Authentication, logging, request IDs, and header
  normalization belong there, not in every route handler.
- **Treat validation as a boundary.** Validate inbound data before it enters the service layer and
  keep the service free of transport concerns.

## Adding a new resource (the recipe)

To add `<thing>`:

1. **Model / schema** - define the request/response shape in `src/models/` or `src/schemas/`.
2. **Repository** - add data access in `src/repositories/<thing>.ts` or `.js`.
3. **Service** - put the business rules in `src/services/<thing>.ts`.
4. **Route** - add endpoints in `src/routes/<thing>.ts`; mount them from the app factory.
5. **Middleware** - add reusable cross-cutting behavior in `src/middleware/` if needed.
6. **Tests** - cover the service and the HTTP contract with `supertest` or the project's runner.

## Conventions

- **Use one app factory.** Build the Express app in a function so tests can create it without
  listening on a port.
- **Keep error handling centralized.** A final error middleware should translate known failures to a
  structured JSON response and leave unexpected ones as 500s.
- **Log with request IDs.** Assign a request ID early in the middleware chain and include it in
  request and response logs.
- **Mask secrets in logs.** Redact passwords, tokens, and API keys before logging request bodies.
- **Prefer config through env + validated defaults.** Keep runtime settings in one config module and
  validate them at startup.
- **Keep the package scripts honest.** If `CLAUDE.md` advertises `test`, `lint`, `typecheck`, or
  `build`, those scripts should exist in `package.json`.

## HTTP status & error mapping

The concrete mapping the route layer applies when translating domain results and errors to HTTP:

**Method -> success status:**

| Operation | Method | Success status |
|---|---|---|
| Create | `POST` | `201 Created` |
| Read / list | `GET` | `200 OK` |
| Full / partial update | `PUT` / `PATCH` | `200 OK` |
| Delete | `DELETE` | `200 OK` or `204 No Content` |

**Domain error -> status:**

| Domain exception | Status |
|---|---|
| not found | `404 Not Found` |
| validation / bad input | `400 Bad Request` or `422 Unprocessable Entity` |
| auth / permission failure | `401 Unauthorized` or `403 Forbidden` |
| conflict / duplicate / state violation | `409 Conflict` |

## Middleware order

Put middleware in a deliberate order:

1. timeout
2. request ID and logging
3. body parsing
4. ingress/header normalization
5. auth and session middleware
6. route mounting
7. 404 handler
8. final error handler

That order keeps the log entries complete, the request object normalized before routes run, and the
error handler last so it can catch every failure path.

## Testing notes

- Use `supertest` for route tests when you need to exercise the whole Express stack.
- Prefer service tests for business logic and route tests for status codes, headers, and middleware
  wiring.
- When a stack exposes `npm run typecheck`, include it in CI and in local smoke checks.

## Anti-patterns to avoid

1. Mounting routes directly in `index.js` instead of through a reusable app factory.
2. Letting route handlers open database connections or contain business rules.
3. Logging raw passwords, tokens, or session secrets.
4. Throwing from asynchronous middleware without passing the error to `next(err)`.
5. Shipping package scripts in `CLAUDE.md` that do not exist in `package.json`.
6. Skipping a dedicated 404 and error middleware, which leaves responses inconsistent.
