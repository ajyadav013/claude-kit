---
name: django-rest-framework-packages
description: Pick the right Django REST Framework third-party package instead of hand-rolling. Maps a need — auth, OpenAPI schema, filtering, async, errors — to a vetted package with maintenance status. Use when adding DRF capability or auditing dependencies.
---

# Django REST Framework third-party packages

DRF keeps a deliberately small core and pushes everything else into third-party packages
(["We **support**, **encourage** and **strongly favor** the creation of Third Party Packages"](https://www.django-rest-framework.org/community/third-party-packages/)).
That means the right move for most DRF capability gaps is *find the package*, not *write the code*.

The catch: DRF's own list is append-only and never pruned. **21 of the packages it currently
recommends have had no release since 2013–2022.** This skill is the filtered view.

## When to use

- Adding a capability to a DRF API: authentication, permissions, OpenAPI schema, filtering,
  pagination, nested routes or writes, file/CSV export, async views, error formatting
- Someone proposes hand-rolling something DRF's ecosystem already solves
- Auditing an existing project's DRF dependencies for abandoned packages
- Reviewing a PR that adds a `djangorestframework-*` / `drf-*` dependency
- Migrating off a dead package (see the "do not adopt" list below)

## Decision order

1. **Core DRF first.** Check the [API Guide](https://www.django-rest-framework.org/api-guide/requests/)
   before reaching for a package. Throttling, versioning, content negotiation, pagination, and
   token auth are all built in. A dependency you don't add is a dependency you don't maintain.
2. **Then the table below.** Prefer an ACTIVE package over a STALE one, even if the STALE one is
   the one DRF's page names first.
3. **Then hand-roll** — a DRF permission class, filter backend, or renderer is usually 20 lines.
   Hand-rolling beats adopting an ABANDONED package every time.

Before adopting anything from this list, verify the current release on PyPI. Status below was
checked **2026-08-14** and packages move.

## Need → package

### Authentication and accounts

| Need | Package | Status | Notes |
|---|---|---|---|
| JWT authentication | `djangorestframework-simplejwt` | ACTIVE (2025-07) | The de facto standard. Django 6 not yet in classifiers. |
| OAuth2 / OIDC **provider** | `django-oauth-toolkit` | ACTIVE (2026-07) | Declares Django 4.2–6.0, Python 3.10–3.14. |
| OIDC **client** auth | `django-pyoidc` | ACTIVE (2026-07) | Django-level, not DRF-specific. Declares Django 6.0. |
| Registration / login / password-reset endpoints | `dj-rest-auth` | ACTIVE (2026-03) | Pairs with `django-allauth`; ships no version classifiers. |
| Same, allauth-independent | `djoser` | ACTIVE (2026-08) | Classifiers cap at Django 5.2. |
| Batteries auth: JWT cookies + social + MFA + typed schema | `drf-auth-kit` | ACTIVE (2026-08) | Young project, very fast cadence — pin tightly. |

Do **not** use `drf-oidc-auth` (2022-09), `hawkrest` (2018-10), `djangorestframework-digestauth`
(2014-01), or `djangorestframework-httpsignature` (2015-05).

### Permissions

| Need | Package | Status | Notes |
|---|---|---|---|
| Object-level permissions | `django-guardian` + `djangorestframework-guardian` | ACTIVE (2026-07 / 2025-07) | The DRF shim carries `DjangoObjectPermissionsFilter`, which DRF removed from core. |
| Declarative, IAM-style policies | `drf-access-policy` | STALE (2023-03) | Still widely used; classifiers cap at Django 3.2. Verify against your Django before adopting. |

Every other permissions package on DRF's page is abandoned — `rest_condition` (2016),
`drf-any-permissions` (2013), `djangorestframework-composed-permissions` (2019),
`dry-rest-permissions` (2018), `drf-psq` (2021). Compose DRF's own `BasePermission` instead;
`&`/`|`/`~` operator support has been in core since 3.9.

### Schema, docs, and typed clients

| Need | Package | Status | Notes |
|---|---|---|---|
| OpenAPI 3 schema, Swagger/Redoc UI, generated TS/Swift/Kotlin clients | `drf-spectacular` | ACTIVE (2026-07) | **The default.** Broadest declared support: Django 2.2–6.0, DRF 3.12–3.17. Not on DRF's official page. |
| Legacy Swagger 2.0 | `drf-yasg` | ACTIVE (2026-02) | No Django 6.0 classifier. Only for existing projects; new work goes to spectacular. |

`drf-spectacular` also ships a camelize hook, which makes `djangorestframework-camel-case` (STALE,
2023-02) unnecessary in most projects.

### Filtering, routing, and query shaping

| Need | Package | Status | Notes |
|---|---|---|---|
| Query-param filtering | `django-filter` | ACTIVE (2026-07, v26.1) | Declares Django 5.2/6.0/6.1. The only real choice; install with the `drf` extra. Not on DRF's official page. |
| Nested resource routes | `drf-nested-routers` | ACTIVE (2026-07) | Maintains an explicit compat matrix. |
| Nested **writes** through serializers | `drf-writable-nested` | ACTIVE (2025-03) | Explicit Django 5.2 classifier. Not on DRF's official page. |
| Client-controlled fields / sparse fieldsets / GraphQL-ish querying | `django-restql` | ACTIVE (2025-08) | Prefer over `drf-flex-fields` (STALE 2023-03) and `djangorestframework-queryfields` (STALE 2023-11). |
| Caching, bulk routes, extended viewsets | `drf-extensions` | ACTIVE (2025-04) | No Django 6.0 classifier yet. |

Avoid `django-url-filter` (2020-02, still pre-alpha), `drf-url-filters` (2017-06),
`djangorestframework-chain` (2013-12).

### Serializers and fields

| Need | Package | Status | Notes |
|---|---|---|---|
| GeoJSON / GIS | `djangorestframework-gis` | ACTIVE (2026-05) | Already tracks Django 6.0. |
| JSON:API spec compliance | `djangorestframework-jsonapi` | ACTIVE (2025-10) | Parser + renderer + serializers in one. |
| Pydantic models as fields / schemas | `django-pydantic-field` | ACTIVE (2026-02) | Declares Django 3.0–6.0. Better maintained than `drf-pydantic` (ACTIVE 2025-12, but no Django pin at all). |
| Serializers from dataclasses | `djangorestframework-dataclasses` | ACTIVE (2025-05) | `ModelSerializer` equivalent for dataclasses. |
| Extra field types (base64 image/file, points, ranges) | `drf-extra-fields` | STALE (2023-08) | No Django 5.x support declared. Check what you actually need — several are now in core. |

`django-rest-framework-mongoengine` (2020-01), `djangorestframework-hstore` (2015-06),
`drf-compound-fields` (2019-09) are dead.

### Async

| Need | Package | Status | Notes |
|---|---|---|---|
| Async views, viewsets, serializers | `adrf` | ACTIVE (2026-06) | The *only* async option for DRF, and still 0.x. Requires Django 4.1+. |

DRF core has no first-class async. If a project is async-first from the start, evaluate
**Django Ninja** (async-native, Pydantic v2) against DRF before committing to `adrf`.
See the `django-async-patterns` skill for the async/ASGI decision.

### Errors, logging, and operations

| Need | Package | Status | Notes |
|---|---|---|---|
| Consistent error response envelope | `drf-standardized-errors` | ACTIVE (2026-04) | Integrates with `drf-spectacular` to document error shapes. |
| Request/response audit logging + admin views | `drf-api-logger` | ACTIVE (2026-07) | Freshest Django 6.0 support of the logging options. |
| Audit logging via middleware | `django-requestlogs` | ACTIVE (2025-03) | No Django 5.1+/6.0 classifiers. |
| Hosted API monitoring / analytics | `apitally` | ACTIVE (2026-06) | Requires a commercial SaaS backend — a procurement decision, not just a dependency. |

### Renderers, parsers, export

| Need | Package | Status | Notes |
|---|---|---|---|
| CSV export | `djangorestframework-csv` | STALE (2023-12) | Untested on Django 5.x/6.x. For simple exports, a `BaseRenderer` subclass over `csv.writer` is ~25 lines. |
| Excel / CSV / SVG from DataFrames | `rest-pandas` | unvetted | Only if pandas is already a dependency. |
| Faster JSON | `drf-ujson2` | ACTIVE (2025-02) | Marginal wins. Measure before adopting; serialization is rarely the bottleneck. |

`djangorestframework-msgpack` (2017-04) and `djangorestframework-rapidjson` (STALE 2023-10) are
not worth the dependency.

### Search, integrations, cosmetics

| Need | Package | Status | Notes |
|---|---|---|---|
| Elasticsearch | — | — | `django-elasticsearch-dsl-drf` is ABANDONED (2022-07, Elasticsearch 7 era). Use `django-elasticsearch-dsl` directly and write the viewset. |
| Haystack search | `drf-haystack` | STALE (2024-11) | Version-less classifiers; inherits Haystack's own maintenance risk. |
| DataTables server-side integration | `djangorestframework-datatables` | STALE (2024-06) | |
| Restyle the browsable API | `drf-redesign` / `drf-restwind` / `drf-material` | ACTIVE (2025-08) | Purely cosmetic. Skip in production APIs where the browsable renderer is disabled anyway. |

### Not on DRF's page, but nearly always needed

| Need | Package | Status |
|---|---|---|
| CORS for an SPA frontend | `django-cors-headers` | ACTIVE (2025-09), declares Django 6.0 |
| Media/static on S3, GCS, Azure | `django-storages` | ACTIVE (2025-04) |
| Object-level permission backend | `django-guardian` | ACTIVE (2026-07) |

## Do not adopt — abandoned but still listed by DRF

`djangorestframework-digestauth` (2014-01) · `djangorestframework-httpsignature` (2015-05) ·
`hawkrest` (2018-10) · `drf-oidc-auth` (2022-09) · `rest_condition` (2016-11) ·
`djangorestframework-composed-permissions` (2019-03) · `drf-any-permissions` (2013-07) ·
`dry-rest-permissions` (2018-01) · `drf-psq` (2021-02) · `djangorestframework-chain` (2013-12) ·
`django-url-filter` (2020-02) · `drf-url-filters` (2017-06) · `djangorestframework-msgpack` (2017-04) ·
`djangorestframework-hstore` (2015-06) · `drf-compound-fields` (2019-09) ·
`django-rest-multiple-models` (2018-12) · `drf-typed-views` (2020-06) ·
`djangorestrelationalhyperlink` (2013-08) · `django-rest-framework-mongoengine` (2020-01) ·
`django-elasticsearch-dsl-drf` (2022-07) · `gaiarestframework` (404 on PyPI)

If a project already depends on one of these, treat it as migration debt and say so — don't extend it.

## Reading the status labels

- **ACTIVE** — released on or after 2025-02 (within 18 months of the 2026-08-14 check).
- **STALE** — last release 2023-02 to 2025-01. Often still works; carries real risk on a Django upgrade.
- **ABANDONED** — last release before 2023-02. Do not adopt.
- **unvetted** — on DRF's list, not checked. Verify on PyPI before use.

**Classifiers lag reality.** A missing `Framework :: Django :: 6.0` classifier is weak evidence, not
proof of incompatibility — several ACTIVE packages here work fine on Django 6 without saying so.
Conversely, a recent release with classifiers capped at Django 3.2 (`drf-access-policy`) is a
genuine signal that nobody has tested it recently. Check the repo's CI matrix when it matters.

## Verifying current status

    pip index versions <package>
    uv pip show <package>

Or read `https://pypi.org/project/<package>/` for the release date and classifier list. The DRF
grid on [Django Packages](https://www.djangopackages.com/grids/g/django-rest-framework/) carries
community usage counts, which are a better popularity signal than DRF's own unordered page.

## References

- `references/catalog.md` — the complete categorized list (every package on DRF's official page,
  plus the essentials it omits), with purpose and status per entry.
- `references/maintenance-status.md` — the raw vetting table: version, last release, compat signal.
- `references/integration-recipes.md` — settings and code wiring for the packages worth defaulting to.

## Related skills

- `django-rest-framework-patterns` — how to use DRF itself (viewsets, serializers, routers, N+1).
- `django-async-patterns` — the async/ASGI decision, and where `adrf` fits.
- `django-react-integration` — CORS, JWT, and `drf-spectacular` → generated TypeScript client.
- `dependency-verification` — verify a package exists and is maintained before adding it.
