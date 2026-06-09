---
name: smoke-test
description: Quick health check — verifies all services are running and basic user flow works. Use before starting development or after deployment.
argument-hint: [optional: "backend-only" or "frontend-only"]
disable-model-invocation: true
---

Run a smoke test across the stack. Scope: $ARGUMENTS (default: full stack).

## Steps

### 1. Backend Health

```bash
# Liveness probe (always 200 if process is up)
curl -sf http://localhost:8000/_healthz && echo "PASS: backend liveness" || echo "FAIL: backend not responding"

# Readiness probe (checks dependencies like DB, cache, etc.)
curl -sf http://localhost:8000/_readyz && echo "PASS: backend readiness (dependencies healthy)" || echo "FAIL: backend not ready — check dependencies"
```

If `_readyz` fails, check the project's dependencies (DB, cache, …) using whatever process or
service manager the project uses:
```bash
# List the running services and confirm each dependency is up and healthy,
# then tail the failing dependency's logs to see why readiness failed.
```

### 2. Frontend Health

```bash
curl -sf http://localhost:3000 > /dev/null && echo "PASS: frontend serving" || echo "FAIL: frontend not responding on port 3000"
```

If the frontend uses a dev server, it may be on a different port:
```bash
curl -sf http://localhost:5173 > /dev/null && echo "PASS: frontend serving (dev)" || echo "FAIL: frontend not responding"
```

### 3. Auth Flow (requires running backend)

```bash
# Register or login with a test user
curl -sf -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.local","password":"TestPass123!"}' \
  -c /tmp/smoke-cookies.txt \
  && echo "PASS: login" || echo "FAIL: login failed"
```

### 4. Authenticated Endpoint

```bash
# Hit dashboard or user-info endpoint with session cookie
curl -sf http://localhost:8000/v1/auth/me \
  -b /tmp/smoke-cookies.txt \
  && echo "PASS: authenticated endpoint" || echo "FAIL: session/auth broken"
```

### 5. Cleanup

```bash
rm -f /tmp/smoke-cookies.txt
```

## Report

After running all steps, summarize:

| Check | Status |
|-------|--------|
| Backend liveness | PASS/FAIL |
| Backend readiness (dependencies) | PASS/FAIL |
| Frontend serving | PASS/FAIL |
| Login flow | PASS/FAIL |
| Authenticated endpoint | PASS/FAIL |

If any check fails, report the failure details and suggest fixes before proceeding with development.
