---
schema_version: 1
id: django-react-integration
description: Wiring a React or SPA frontend to Django — same-origin vs separate-origin topologies, CorsMiddleware ordering, session vs JWT auth, a typed client from drf-spectacular, static/media split. Use when a Django project has a React/SPA frontend.
invocation: implicit
capabilities: []
request_input:
  mode: none
pause_for_human: []
references: []
---

Use this when a Django project serves, or is consumed by, a React or other SPA frontend. It covers
the two topologies, and the handful of things that are wrong by default in each.

## When to use

- Standing up a React frontend against a Django API
- Choosing between serving the SPA from Django and deploying it separately
- CORS requests failing, or succeeding but dropping cookies
- Deciding session auth vs JWT for a browser client
- Generating a typed API client so the frontend stops hand-writing response types
- Static and media files 404ing in production

## Pick a topology first

Almost every problem below is a consequence of this choice, so make it explicitly.

### A. Same origin — Django serves the bundle

cookiecutter-django's `frontend_pipeline` option (Gulp or Webpack) sets this up. Django serves the
HTML shell and the built assets; the SPA calls `/api/...` on its own origin.

- **No CORS at all.** Same origin means the whole class of problems does not exist.
- **Session auth works out of the box**, cookies included.
- Simplest deployment: one service, one domain.
- Cost: frontend and backend deploy together, and the frontend build is coupled to Django's static
  pipeline.

**The dev port trap.** With Gulp or Webpack, `npm run dev` runs the asset build and Django in
parallel, and the URL to open is **`http://localhost:3000`**. Opening `:8000` still serves pages —
Django is up — but unstyled, with every static asset 404ing. It looks like a broken install. It is
the wrong port. With `frontend_pipeline: None` or Django Compressor, `:8000` is correct.

### B. Separate origins — Vite/Next dev server, independent deploy

The frontend is its own app on its own origin, talking to Django over HTTP.

- Independent deploys and independent scaling.
- Frontend tooling stays idiomatic (Vite HMR, the framework's own dev server).
- Cost: CORS, cookie policy, and auth all become real decisions.

## Separate-origin wiring

### CORS middleware order is not optional

```python
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",       # MUST be above CommonMiddleware
    "django.middleware.common.CommonMiddleware",
    ...
]

CORS_ALLOWED_ORIGINS = ["https://app.example.com"]   # never CORS_ALLOW_ALL_ORIGINS in production
CORS_ALLOW_CREDENTIALS = True                        # only if using session/cookie auth
```

`CorsMiddleware` must sit **above** `CommonMiddleware`. Below it, `CommonMiddleware` can respond or
redirect before the CORS headers are attached, and the preflight fails in a way that looks like a
server error rather than a configuration mistake.

Enumerate origins. `CORS_ALLOW_ALL_ORIGINS = True` with `CORS_ALLOW_CREDENTIALS = True` is rejected
by browsers anyway, and is a hole regardless.

### Session vs JWT for a browser client

| | Session cookies | JWT |
|---|---|---|
| Storage | `HttpOnly` cookie — unreachable from JS | Usually JS-readable storage |
| XSS exposure | Token cannot be exfiltrated by script | Token can be stolen |
| Revocation | Immediate, server-side | Not until expiry, without a denylist |
| CSRF | Needs protection | Not applicable with header auth |
| Cross-origin | Needs `SameSite=None; Secure` + `CORS_ALLOW_CREDENTIALS` | Simpler |
| Mobile / third-party clients | Awkward | Natural fit |

**Default to session auth for a first-party browser SPA.** The `HttpOnly` cookie is a real security
property that JWT-in-localStorage gives away, and "we might add a mobile app" is not a reason to
take that loss today.

Reach for JWT when clients are genuinely not browsers on your domain, or when the API is consumed
by third parties.

With session auth cross-origin, you need:

```python
SESSION_COOKIE_SAMESITE = "None"   # cross-site requests
SESSION_COOKIE_SECURE = True       # required whenever SameSite=None
CSRF_TRUSTED_ORIGINS = ["https://app.example.com"]
```

and the frontend must send `credentials: "include"` and echo the CSRF token on unsafe methods.

## Generate the client, do not hand-write it

`drf-spectacular` produces an OpenAPI 3 schema; generate TypeScript from it rather than
maintaining response interfaces by hand.

```bash
uv run python manage.py spectacular --file schema.yml
npx openapi-typescript schema.yml -o src/api/schema.d.ts
```

Wire both into CI: regenerate and fail on a diff. Otherwise the generated types drift from the
serializers and the type checker starts confidently lying. Hand-written interfaces have the same
failure mode with no signal at all.

## Production static and media

Two different things, routinely conflated:

- **Static** — your CSS, JS, images. Collected by `collectstatic`, served by whitenoise or a CDN.
- **Media** — user uploads. Never served by Django in production; use django-storages against S3,
  GCS, or Azure.

```python
STATIC_ROOT = BASE_DIR / "staticfiles"          # collectstatic target
STATIC_URL = "/static/"
```

The SPA bundle is *static*. Under topology B it is usually served entirely by the frontend host or
CDN and Django serves only the API — in which case Django's static config still matters for the
admin and DRF's browsable API, which is why it 404s in a way nobody expects.

`DEBUG = False` stops Django serving static files itself. A deploy that worked in development and
serves unstyled pages in production is almost always a missing `collectstatic` or a missing
whitenoise entry in `MIDDLEWARE`.

## Anti-patterns to avoid

1. **`CorsMiddleware` below `CommonMiddleware`** — preflight fails opaquely.
2. **`CORS_ALLOW_ALL_ORIGINS = True` in production** — and it silently will not work with
   credentials anyway.
3. **JWT in `localStorage` for a first-party browser app** — trades an `HttpOnly` cookie for XSS
   exposure, usually for no gain.
4. **Long-lived access tokens with no rotation** — a stolen token stays valid for its full life.
5. **Hand-written TypeScript response types** — drift from the serializers with no signal.
6. **Schema generated locally and committed by hand** — same drift, one step removed.
7. **Serving user uploads through Django in production** — ties file delivery to app workers.
8. **Debugging the `:3000` / `:8000` mix-up as a broken install** — check the port before
   reinstalling anything.
9. **`SameSite=None` without `Secure`** — browsers reject the cookie outright.
10. **Assuming topology B needs no Django static config** — the admin and browsable API still do.

## References

- `django-rest-framework-patterns` — the API this frontend consumes; drf-spectacular setup
- `django-service-patterns` — cookiecutter's `frontend_pipeline` options
- `security-and-hardening` — CSRF and cookie hardening, stack-agnostic
