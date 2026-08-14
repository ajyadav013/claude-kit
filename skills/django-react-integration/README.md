# django-react-integration

Encodes wiring a React or SPA frontend to a Django backend. Starts from the topology choice —
Django serving the bundle on one origin, versus an independently deployed frontend on another —
because nearly every CORS, cookie, auth, and static-file problem downstream is a consequence of
that decision.

Rides the Django backend lane; applies when a React or other SPA frontend is present.

## What this skill covers

- The two topologies and what each costs
- The cookiecutter `frontend_pipeline` **`:3000` vs `:8000`** trap, which presents as a broken
  install rather than a wrong port
- `CorsMiddleware` above `CommonMiddleware`, and why the failure is opaque when it is not
- Session vs JWT for browser clients as a comparison table, with a default recommendation and the
  cases that override it
- `SameSite=None; Secure`, `CORS_ALLOW_CREDENTIALS`, and `CSRF_TRUSTED_ORIGINS` for cross-origin
  session auth
- Generating a TypeScript client from drf-spectacular, and failing CI on schema drift
- The static-vs-media split, and why the admin still needs static config in a separate-origin
  deploy

## Provenance

Written for **Django 6.1** with DRF and drf-spectacular. The topology framing follows
cookiecutter-django's `frontend_pipeline` options, since that is where most Django + React projects
make the choice implicitly rather than deliberately.

## How to apply

1. Name the topology before debugging anything — most symptoms are downstream of it.
2. Separate origins: fix middleware order first, then cookie policy, then auth.
3. Generate the API client and gate it in CI; do not hand-write response types.
4. For the API itself, see `django-rest-framework-patterns`.
