---
name: load-testing
description: Load and stress test API endpoints under concurrency. Use when measuring throughput/latency under load, validating an SLO before launch, sizing the connection pool, or hunting a performance cliff. Covers ramp profiles, thresholds (p95/p99 latency, error rate), authenticated + rate-limited endpoints, and reading results. Distinct from frontend performance-optimization (web vitals/bundles).
---

# Load Testing

Measure how a service behaves under concurrency — before users find the cliff. This is the missing
half of the kit's performance story: `performance-optimization` covers the **frontend** (web vitals,
bundles, rendering); this skill drives **concurrent load against an API** to validate the SLOs that
`.claude/rules/devops-observability.md` and the `observability-engineer` define. Most cliffs are
data-layer bound, so if your stack ships a DB-performance reviewer or rule, cross-check it.

## When to Use

- Before a launch, or after a change to a hot endpoint.
- To validate an SLO ("p95 `POST /api/...` < 200ms at 50 rps").
- To size the service's connection-pool and worker settings.
- To reproduce a latency/timeout complaint under controlled load.

## Tool

Use whatever load tool the project standardizes on — **k6** (lightweight, scriptable, good
thresholds) and **Locust** (scenarios in Python) are common choices. The methodology below is
tool-agnostic; the example uses k6. Adapt the routes, auth, and tool to your stack.

```javascript
// example (k6):  k6 run load/login-and-list.js   — adapt routes/auth to your API
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE || 'http://localhost:8000';

export const options = {
  scenarios: {
    ramp: { executor: 'ramping-vus', startVUs: 0,
      stages: [ { duration: '30s', target: 50 }, { duration: '2m', target: 50 }, { duration: '30s', target: 0 } ] },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],                 // < 1% errors
    'http_req_duration{name:list}': ['p(95)<200'],  // p95 < 200ms on the list call
  },
};

export function setup() {
  // If the API uses cookie/session or token auth, authenticate ONCE here and reuse per VU.
  const res = http.post(`${BASE}/api/login`,
    JSON.stringify({ email: __ENV.EMAIL, password: __ENV.PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } });
  check(res, { 'login 200': (r) => r.status === 200 });
  return { cookies: res.cookies };
}

export default function (data) {
  const res = http.get(`${BASE}/api/items`, { jar: http.cookieJar(), tags: { name: 'list' } });
  check(res, { 'list 200': (r) => r.status === 200 });
  sleep(1);
}
```

## Method

1. **Pick the target + SLO.** One endpoint/flow per test; define the pass threshold up front (p95 latency, error rate, target rps).
2. **Use realistic data + auth.** Authenticate once and reuse the session/token. Seed realistic data so any tenant-scoped or filtered queries hit realistic row counts.
3. **Mind rate limits.** Throttled endpoints (e.g. auth) — either test below the limit, or test the limiter itself deliberately and expect 429s.
4. **Ramp, don't spike** (unless spike is the test). Warm up, hold, ramp down.
5. **Watch the service while it runs:** tail the service's logs, the database's active-connection count, and CPU. The bottleneck is usually the data layer (N+1, missing index, pool exhaustion) — cross-check your stack's DB-performance guidance.
6. **Read results:** p95/p99 (not just avg), error rate, throughput plateau. A latency knee as concurrency climbs = saturation (pool/CPU/lock).

## Thresholds to start from

- Error rate < 1% under target load.
- p95 within the endpoint's SLO; p99 no more than ~2–3× p95 (bigger gap = tail problems).
- Throughput scales with concurrency until a plateau — find where it flattens.

## Rules

1. **Never load-test production** without explicit approval — test a staging/local stack. See `.claude/rules/human-in-the-loop.md`.
2. Tie every run to an SLO; a load test without a pass/fail threshold is just noise.
3. When you find a cliff, hand the specifics to the data-layer/dev lane — don't guess the fix here.
4. Keep scripts in `load/`; record the run + result in `docs/performance/`.

> Adapted from a portfolio project's load-testing skill; generalized to be stack- and tool-agnostic for claude-kit.
