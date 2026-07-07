---
paths:
  - "**/*.go"
---

# Go backend patterns (net/http)

Stack-specific conventions for the backend. This overlay is installed into `.claude/rules/` only when
the **Go · net/http (stdlib)** stack is selected. It complements the generic rules — read
`.claude/rules/code-organization.md`, `.claude/rules/design-patterns.md`, and `.claude/rules/testing.md`
first; this file makes them concrete for Go.

## Stack

- **Go 1.22+**, standard-library **`net/http`** with the method-aware `http.ServeMux`
  (`mux.HandleFunc("POST /things/{id}", ...)`), `encoding/json`, `context`, `log/slog`.
- Tests: the stdlib **`testing`** package (table-driven) + **`net/http/httptest`**; no third-party
  runner required. `go test -race ./...` for anything concurrent.
- Tooling: the compiler **is** the type checker — `go build ./...` and `go vet ./...` must pass;
  `gofmt`/`goimports` is non-negotiable formatting.

Run the project's own commands for these tasks (see the **Commands** section of `CLAUDE.md`): install,
run/dev, test, lint+vet, format, build.

> Build-green for Go = `go vet ./...` + `go build ./...` + `go test ./...` all green. The compiler
> replaces a separate type-check step; treat a vet finding as a build failure, not a warning.

## Layered architecture (never skip a layer)

```
handler (internal/http/)     HTTP only: decode+validate request, call service, map errors → status
  → service (internal/<domain>/)  business logic; returns DOMAIN errors; no net/http imports
    → repository (internal/<domain>/store)  data access only: queries, returns structs or a not-found error
      → model (internal/<domain>/)  plain structs
request/response DTOs (internal/http/)  the JSON contract — separate from domain structs
```

Rules of thumb:
- **Handlers stay thin.** No queries, no business rules. Decode into a request DTO, call the service,
  translate domain errors to a status code with a small JSON error body.
- **Services never import `net/http`.** They return sentinel/typed domain errors (e.g.
  `ErrThingNotFound`); the handler decides the status. This keeps services testable without HTTP.
- **Propagate `context.Context` as the first argument** of every service/repository call; derive
  request-scoped deadlines from `r.Context()`. Never store a `Context` in a struct.
- **DTOs are separate from domain structs.** Don't JSON-encode a domain/storage struct directly; map
  to a response DTO so storage fields never leak into the contract.

## Adding a new resource (the recipe)

To add `<thing>`:

1. **Model** — `internal/<thing>/<thing>.go`: the domain struct + `ErrThingNotFound`.
2. **DTOs** — `internal/http/<thing>_dto.go`: `<Thing>CreateRequest`, `<Thing>Response`, with a
   `Validate()` method (no validation framework needed for stdlib).
3. **Repository** — `internal/<thing>/store/<thing>.go`: data access; returns `(*Thing, error)` with
   the not-found sentinel; takes `ctx` first.
4. **Service** — `internal/<thing>/service.go`: business logic over the repository.
5. **Handler** — `internal/http/<thing>.go`: decode → `Validate()` → service → encode; register routes
   on the `ServeMux` with method-aware patterns.
6. **Migration** — see `.claude/rules/database-*.md` for the database-specific migration recipe.
7. **Tests** — `internal/<thing>/service_test.go` (table-driven) and an `httptest` handler test:
   cover create, list, get-missing (404), invalid body (400).

## Conventions

- **Errors wrap, never swallow.** Return `fmt.Errorf("doing X: %w", err)`; inspect with
  `errors.Is`/`errors.As`. A handler maps a known sentinel to its status and everything else to 500
  with a generic body — never leak internal error strings to the client.
- **`defer rows.Close()` / `defer f.Close()`** for every resource; check the error on writes/commits.
- **Concurrency:** every goroutine has a clear owner and lifetime tied to a `context`; never start a
  naked `go f()` whose completion no one waits for. Run `go test -race` on concurrent code.
- **No `panic` for expected failures** — return an `error`. Reserve `panic` for truly unrecoverable
  programmer errors; recover at the top of a handler only to convert to a 500.
- **Type everything; document exported identifiers.** Every exported func/type gets a doc comment
  (starting with its name) per `.claude/rules/documentation.md`; `go vet` and `gofmt` must pass.
- **Config via env** read once at startup into a typed struct; never scatter `os.Getenv` through the
  code. Document new vars in `.env.example` and the README.
- **Migrations are reviewed, not trusted** — read every generated migration before applying. See the
  database overlay rule for the exact tool and commands.
