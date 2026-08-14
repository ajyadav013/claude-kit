# django-rest-framework-patterns

Encodes the DRF layer: the request-flow ladder from router to response, thin ViewSets delegating to
services, serializers as the wire contract rather than a logic home, and the `get_queryset()` fixes
for the serializer-driven N+1 that dominates DRF performance work. Also covers drf-spectacular,
django-filter, SimpleJWT, pagination defaults, and when Django Ninja is the better choice.

## What this skill covers

- The request-flow ladder — Router → ViewSet → `get_queryset()` → filter backends → Serializer
- Thin ViewSets that delegate workflows to `services.py`
- Explicit serializer `fields`; splitting read and write serializers when they diverge
- N+1: `select_related` vs `prefetch_related` vs `Prefetch`, and Django 6.1 fetch modes as a
  backstop rather than a substitute
- Query-count assertions so an N+1 fix cannot silently regress
- Pagination on by default, django-filter, SimpleJWT, CORS middleware ordering
- drf-spectacular, and generating the schema in CI so the contract cannot drift
- Django Ninja as the async-first alternative, and why not to run both

## Provenance

Written for **Django 6.1** with DRF. Notes DRF's lack of first-class async and points at `adrf` and
its limits in `django-async-patterns`. Ninja is covered because cookiecutter-django offers it
alongside DRF at generation time.

## How to apply

1. Read the request-flow ladder first — it tells you which step a given fix belongs in.
2. Shape tenancy and relations in `get_queryset()`, never in the serializer.
3. Add a `django_assert_num_queries` test alongside any N+1 fix.
4. For the workflow the view delegates to, see `django-service-patterns`.
5. For a browser client on another origin, see `django-react-integration`.
