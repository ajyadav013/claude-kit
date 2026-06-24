# sample-app — `taskapi` (Go / net-http, stdlib only)

The real application the [captured `/sdlc` run](../README.md) was executed against: a tiny task API
built with Go's standard-library `net/http` (Go 1.22+ method routing). **Zero third-party
dependencies**, so every gate check reproduces anywhere Go is installed.

```
go.mod
main.go         # wires the server on 127.0.0.1:8080
server.go       # routes: GET /health, GET /tasks, POST /tasks, DELETE /tasks/{id}
store.go        # concurrency-safe in-memory Store (Add / List / Delete)
server_test.go  # httptest-based tests, incl. the mux-level regression for the id-aliasing bug
run-checks.sh   # the exact build + vet + gofmt + test commands behind the gate verdicts
```

This is the **post-run** state — it already includes the `DELETE /tasks/{id}` feature *and* the fix
the devils-advocate forced (rejecting non-canonical ids). The feature diff vs the baseline is in
[`../captured-bundle/git/changes.diff`](../captured-bundle/git/changes.diff).

## Reproduce the gate checks

```bash
bash run-checks.sh
# or:
go test ./... -v -cover -count=1   # 7 tests, ~85% coverage
go vet ./... && gofmt -l .
```

> It's a demo: in-memory only, no auth, single-process. The [captured security review](../captured-bundle/evidence/security-clear.txt)
> spells out what production would additionally require.
