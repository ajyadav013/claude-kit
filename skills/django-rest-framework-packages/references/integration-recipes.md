# Integration recipes

Wiring for the packages worth defaulting to. Every snippet assumes `config/settings/base.py` in
the cookiecutter-django two-tier layout; adjust the module path for a flat project.

Verify current install syntax against each project's own docs — these show the shape, not a
substitute for reading the README.

## The default DRF API stack

For a new DRF API, this is the set that earns its place:

    drf-spectacular         # OpenAPI 3 schema + typed clients
    django-filter           # query-param filtering
    djangorestframework-simplejwt   # JWT auth (or dj-rest-auth for full account endpoints)
    django-cors-headers     # if a browser client calls the API
    drf-standardized-errors # consistent error envelope
    drf-nested-routers      # only if the resource tree is genuinely nested

Everything else should answer a specific, present need.

## drf-spectacular — schema and typed clients

    INSTALLED_APPS += ["drf_spectacular"]

    REST_FRAMEWORK = {
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    }

    SPECTACULAR_SETTINGS = {
        "TITLE": "Project API",
        "VERSION": "1.0.0",
        "SERVE_INCLUDE_SCHEMA": False,
        # Emit camelCase to a JS client without adding djangorestframework-camel-case:
        # "CAMELIZE_NAMES": True,
    }

URLs:

    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    ]

Generate a TypeScript client for a React frontend from the emitted schema:

    python manage.py spectacular --file schema.yml
    npx openapi-typescript schema.yml -o src/api/schema.d.ts

Annotate anything the introspector can't infer with `@extend_schema` rather than hand-writing the
schema. A `ValidationError` shape that isn't in the schema is a lie the frontend will trust.

## django-filter — query-param filtering

Install with the DRF extra: `django-filter[drf]`.

    INSTALLED_APPS += ["django_filters"]

    REST_FRAMEWORK = {
        "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    }

Per-viewset:

    class OrderViewSet(ModelViewSet):
        filterset_fields = ["status", "customer"]

        def get_queryset(self):
            # Filtering does not remove the N+1 — fix it here, before the serializer runs.
            return Order.objects.select_related("customer").prefetch_related("items")

`django-filter` uses CalVer and drops old Django releases aggressively. Pin it and read the
changelog on upgrade.

## djangorestframework-simplejwt — JWT auth

    REST_FRAMEWORK = {
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
    }

    from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

    urlpatterns += [
        path("api/token/", TokenObtainPairView.as_view()),
        path("api/token/refresh/", TokenRefreshView.as_view()),
    ]

For a browser SPA on the same site, session auth over HTTPS with CSRF is simpler and safer than
JWT in `localStorage`. Reach for JWT when the client is mobile, a third-party service, or on a
different origin where cookies are impractical. If you do use JWT in a browser, put it in an
`HttpOnly` cookie — `dj-rest-auth` and `drf-auth-kit` both support that out of the box.

## django-cors-headers — SPA access

    INSTALLED_APPS += ["corsheaders"]

    MIDDLEWARE = [
        "corsheaders.middleware.CorsMiddleware",   # MUST be above CommonMiddleware
        "django.middleware.common.CommonMiddleware",
        # ...
    ]

    CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]   # Vite dev server
    CORS_ALLOW_CREDENTIALS = True                       # only if using cookie auth

Never ship `CORS_ALLOW_ALL_ORIGINS = True` to production. Set the real origins per environment.

## drf-standardized-errors — consistent error shape

    INSTALLED_APPS += ["drf_standardized_errors"]

    REST_FRAMEWORK = {
        "EXCEPTION_HANDLER": "drf_standardized_errors.handler.exception_handler",
    }

    # Document the error shape in the schema too:
    SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"] = {
        "ValidationErrorEnum": "drf_standardized_errors.openapi_serializers.ValidationErrorEnum.choices",
    }

Pairs with `drf-spectacular` so error responses appear in the generated client instead of being
discovered at runtime.

## django-guardian + djangorestframework-guardian — object-level permissions

    INSTALLED_APPS += ["guardian"]

    AUTHENTICATION_BACKENDS = [
        "django.contrib.auth.backends.ModelBackend",
        "guardian.backends.ObjectPermissionBackend",
    ]

    from rest_framework_guardian.filters import ObjectPermissionsFilter

    class DocumentViewSet(ModelViewSet):
        permission_classes = [DjangoObjectPermissions]
        filter_backends = [ObjectPermissionsFilter]

`DjangoObjectPermissionsFilter` was removed from DRF core; the shim package is where it lives now.

Object-level permissions add a join per request. If the rule is expressible as a queryset filter
(`Document.objects.filter(team__members=request.user)`), do that instead — it's faster and simpler.

## adrf — async DRF views

    from adrf.viewsets import ViewSet

    class ReportViewSet(ViewSet):
        async def list(self, request):
            reports = [r async for r in Report.objects.filter(owner=request.user)]
            return Response(ReportSerializer(reports, many=True).data)

Constraints worth knowing before adopting:

- `adrf` is still 0.x. Pin it exactly and read the changelog on every bump.
- DRF's own permission, throttle, and filter classes remain sync — you get async *views*, not an
  async stack. Middleware and auth still context-switch.
- Disable `CONN_MAX_AGE` under ASGI and use the database's own pooling.
- Code needing transaction semantics should be one sync function called via `sync_to_async`.

If the project is async-first from day one, evaluate Django Ninja against DRF+`adrf` before
committing. See `django-async-patterns`.

## drf-nested-routers — nested resources

    from rest_framework_nested import routers

    router = routers.SimpleRouter()
    router.register(r"projects", ProjectViewSet)

    tasks_router = routers.NestedSimpleRouter(router, r"projects", lookup="project")
    tasks_router.register(r"tasks", ProjectTaskViewSet, basename="project-tasks")

Nest one level. Two or more is a sign the resource model wants flattening with a filter instead:
`/tasks/?project=<id>` is easier to cache, paginate, and reason about than `/projects/1/tasks/2/comments/`.

## Auditing an existing project

    pip list --outdated
    pip index versions <suspect-package>

Cross-check every `drf-*` and `djangorestframework-*` dependency against the abandoned list in
`maintenance-status.md`. Anything that matches is migration debt — flag it in review with the
replacement named, not just the problem.
