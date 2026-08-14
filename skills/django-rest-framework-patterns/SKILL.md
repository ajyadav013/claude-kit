---
name: django-rest-framework-patterns
description: Django REST Framework — ViewSets and routers, serializer boundaries, the request-flow ladder, fixing serializer N+1 in get_queryset, drf-spectacular, django-filter, SimpleJWT, pagination. Use when building or reviewing a Django REST API.
---

Standardize the DRF layer: what belongs in a ViewSet, what belongs in a serializer, and where the
queryset gets shaped so the API does not issue a query per row.

Targets **Django 6.1** with DRF. Django Ninja is covered as the documented alternative, since
cookiecutter-django offers both.

## When to use

- Adding or reviewing a REST endpoint on a Django project
- Diagnosing a list endpoint that is slow in proportion to page size
- Deciding between a ViewSet and an APIView
- Wiring OpenAPI, filtering, JWT auth, or pagination
- Choosing between DRF and Django Ninja for a new API

## The request-flow ladder

Every DRF request walks the same path. Knowing the order tells you where a fix belongs.

```
HTTP request
  → Router          resolves the URL to a ViewSet action
  → ViewSet         permission_classes, then authentication
  → get_queryset()  the base rows, and where select_related/prefetch_related go
  → filter_backends django-filter, search, ordering
  → Serializer      field selection and validation — the API contract
  → Response        rendered
```

Two rules follow directly:

- **Shape the queryset in `get_queryset()`.** It is the only step that runs before the serializer
  touches a row.
- **Do not query in a serializer.** A serializer that reaches for `obj.related.all()` runs once per
  row, and no amount of caching downstream fixes it.

## Core conventions

### ViewSet, thin

```python
class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["status", "customer"]

    def get_queryset(self):
        return (
            Order.objects
            .filter(customer__org=self.request.user.org)   # tenancy first
            .select_related("customer")                     # FK / O2O
            .prefetch_related("items__product")             # M2M / reverse FK
        )

    def perform_create(self, serializer):
        create_order(user=self.request.user, **serializer.validated_data)
```

The view parses, authorises, and delegates. The workflow lives in `services.py` (see
`django-service-patterns`), which keeps it callable from a management command or a Celery task.

Use `ModelViewSet` when the resource really is CRUD. Reach for `APIView` when the endpoint is an
action rather than a resource — `POST /orders/{id}/refund` is clearer as an explicit view or a
`@action` than as a contorted `partial_update`.

### Serializers are the contract, not the logic

- Enumerate `fields` explicitly. `fields = "__all__"` means the next model field you add is
  published to the API without anyone deciding to.
- Validate in `validate_<field>` and `validate`; both raise `serializers.ValidationError`, which
  DRF maps to 400.
- Separate read and write serializers once they diverge, via `get_serializer_class()`. Forcing one
  class to do both produces a thicket of `read_only` and `required=False`.

### The N+1 that dominates DRF

The failure mode is always the same: a serializer with a nested field, and a queryset that did not
prefetch it. One query becomes one-per-row and the endpoint degrades with page size.

Fix it in `get_queryset()`:

| Relation | Use |
|---|---|
| Forward FK, one-to-one | `select_related` (SQL join, one query) |
| Reverse FK, many-to-many | `prefetch_related` (second query, joined in Python) |
| Nested prefetch with its own filter | `Prefetch("items", queryset=Item.objects.select_related("product"))` |

**Django 6.1** adds *fetch modes*, where `FETCH_PEERS` collapses most unplanned N+1 into two
queries. Treat it as a backstop for the case you missed, not a reason to stop declaring what the
endpoint needs — an explicit `select_related` still documents intent and survives an ORM upgrade.

Verify with `django-debug-toolbar` locally, or assert query counts in tests:

```python
def test_order_list_is_constant_query_count(client, django_assert_num_queries):
    with django_assert_num_queries(4):
        client.get("/api/orders/")
```

A count assertion is the only thing that keeps an N+1 fix from silently regressing.

### Pagination, filtering, auth

- **Pagination on by default.** Set `DEFAULT_PAGINATION_CLASS` and `PAGE_SIZE` globally; an
  unpaginated list endpoint is a production incident waiting for the table to grow.
  `LimitOffsetPagination` is fine for admin surfaces; cursor pagination is the one that stays
  correct while rows are being inserted.
- **django-filter** via `DjangoFilterBackend` and `filterset_fields`, so filters are declared
  rather than parsed out of `request.query_params` by hand.
- **djangorestframework-simplejwt** for token auth. Keep access tokens short-lived and rotate
  refresh tokens. If the client is a browser on your own domain, session auth is simpler and
  avoids storing a token in JS — see `django-react-integration`.
- **django-cors-headers** when the frontend is a separate origin, and `CorsMiddleware` must sit
  above `CommonMiddleware`.

### OpenAPI with drf-spectacular

`drf-spectacular` generates OpenAPI 3 from the serializers and view annotations, and that schema is
what generates a typed client for the frontend. Annotate anything it cannot infer:

```python
@extend_schema(responses=RefundSerializer, request=RefundRequestSerializer)
def refund(self, request, pk=None): ...
```

Generate the schema in CI and fail on a diff, the same way migrations are checked — otherwise the
published contract drifts from the code that serves it.

### Django Ninja, the alternative

Django Ninja is async-first and uses Pydantic v2 for schemas, so it feels like FastAPI inside
Django. It is a reasonable choice for a new async-heavy API.

Choose DRF when you want the larger ecosystem (ViewSets, permissions, browsable API, the filter and
auth packages above) or the team already knows it. Choose Ninja when the API is async throughout
and you would otherwise be fighting DRF's sync design — DRF has **no first-class async support**,
and the `adrf` bridge has real limits (see `django-async-patterns`).

Do not run both in one project. Two API frameworks means two auth integrations, two schema
generators, and two sets of conventions.

## Anti-patterns to avoid

1. **`fields = "__all__"`** — publishes every future model field, including the one you add for
   internal bookkeeping.
2. **Queries inside a serializer method field** — the canonical N+1.
3. **Business logic in `create()` / `update()`** — unreachable from anything that is not an HTTP
   request.
4. **No pagination on a list endpoint** — fine until the table is large, then it is an outage.
5. **Filtering by hand from `request.query_params`** — undocumented, unvalidated, and invisible to
   the OpenAPI schema.
6. **Tenancy applied in the serializer** — authorization belongs in `get_queryset()`, before any
   row is loaded. Filtering after the fact has already leaked the row.
7. **Long-lived JWTs with no rotation** — a stolen token stays valid for its whole lifetime.
8. **Returning model instances from a service into a view untouched** — let the serializer own the
   wire shape.
9. **Schema generated by hand** — it drifts from the code within a sprint.
10. **`AllowAny` as the project default permission** — make the default restrictive and open
    endpoints deliberately.

## References

- `django-service-patterns` — where the services layer these views call belongs
- `django-async-patterns` — async DRF via `adrf`, and its limits
- `django-react-integration` — session vs JWT, CORS ordering, generated TypeScript clients
- `api-and-interface-design` — the stack-agnostic API contract rules, installed alongside this skill
