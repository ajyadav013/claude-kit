# Maintenance status — vetted set

Checked against PyPI on **2026-08-14**. Data is version, release date, and declared support
(classifiers plus README-stated requirements). `requires_dist` was not readable, so the compat
column mixes both sources.

**Labels:** ACTIVE = released on or after 2025-02 · STALE = 2023-02 to 2025-01 ·
ABANDONED = before 2023-02.

Classifier metadata lags reality. Treat a missing `Framework :: Django :: 6.0` as weak evidence.
Treat a *recent* release whose classifiers still cap at an old Django as a strong signal that
nobody has tested it lately.

## Authentication and permissions

| PyPI name | Version | Last release | Declared support | Status |
|---|---|---|---|---|
| `djangorestframework-simplejwt` | 5.5.1 | 2025-07 | Django 4.2–5.2; Python 3.9–3.13 | ACTIVE |
| `django-oauth-toolkit` | 3.4.0 | 2026-07 | Django 4.2–6.0; Python 3.10–3.14 | ACTIVE |
| `dj-rest-auth` | 7.2.0 | 2026-03 | No classifiers; README Django 4.2–6.0, Py 3.10–3.14 | ACTIVE |
| `djoser` | 2.3.4 | 2026-08 | Django 3.2–5.2; DRF ≥3.14; Python 3.9–3.13 | ACTIVE |
| `drf-auth-kit` | 1.8.1 | 2026-08 | README Django 5.0+, DRF 3.0+; Py 3.10–3.14 | ACTIVE |
| `django-pyoidc` | 1.0.13 | 2026-07 | Django 5.2/6.0; Python 3.10–3.14 | ACTIVE |
| `djangorestframework-guardian` | 0.4.0 | 2025-07 | Django 4.2–5.2; Python 3.10–3.13 | ACTIVE |
| `django-guardian` | 3.3.3 | 2026-07 | Django 3.2–5.2; Python 3.10–3.14 | ACTIVE |
| `drf-access-policy` | 1.5.0 | 2023-03 | Django 2.0–3.2; Python 3.6–3.11 | STALE |
| `drfpasswordless` | 1.5.9 | 2023-10 | Only Py 3.6 classifier; README Django 2.2+ | STALE |
| `drf-oidc-auth` | 3.0.0 | 2022-09 | Python 3.7–3.10; beta | ABANDONED |
| `drf-psq` | 1.1.0 | 2021-02 | No classifiers, no description | ABANDONED |

## Schema, filtering, routing

| PyPI name | Version | Last release | Declared support | Status |
|---|---|---|---|---|
| `drf-spectacular` | 0.30.0 | 2026-07 | Django 2.2–6.0; DRF 3.12–3.17; Py 3.6–3.14 | ACTIVE |
| `django-filter` | 26.1 | 2026-07 | Django 5.2/6.0/6.1; Python 3.10–3.14 | ACTIVE |
| `drf-nested-routers` | 0.95.3 | 2026-07 | Django 4.2–5.2; DRF 3.14–3.16; Py 3.10–3.13 | ACTIVE |
| `drf-yasg` | 1.21.15 | 2026-02 | Django 4.0–5.2; DRF 3.13–3.15; Py 3.9–3.13 | ACTIVE |
| `drf-extensions` | 0.8.0 | 2025-04 | Django 3.2/4.2/5.2; Python 3.9–3.12 | ACTIVE |
| `django-url-filter` | 0.3.15 | 2020-02 | Python 2.7/3.4; pre-alpha | ABANDONED |
| `drf-url-filters` | 0.5.1 | 2017-06 | No metadata | ABANDONED |

## Serializers and fields

| PyPI name | Version | Last release | Declared support | Status |
|---|---|---|---|---|
| `djangorestframework-gis` | 1.2.1 | 2026-05 | README Django 4.2–6.0, DRF 3.12–3.17 | ACTIVE |
| `django-pydantic-field` | 0.5.4 | 2026-02 | Django 3.0–6.0; Python 3.10–3.14 | ACTIVE |
| `djangorestframework-jsonapi` | 8.1.0 | 2025-10 | Django 4.2/5.1/5.2; DRF 3.15/3.16; Py 3.9–3.14 | ACTIVE |
| `django-restql` | 0.18.0 | 2025-08 | Classifiers lag (Django 1.11–4.1); DRF ≥3.5 | ACTIVE |
| `drf-pydantic` | 2.9.1 | 2025-12 | No Django classifiers or pin; pydantic v2 | ACTIVE |
| `djangorestframework-dataclasses` | 1.4.0 | 2025-05 | README Django 3.2+, DRF 3.11+ | ACTIVE |
| `drf-writable-nested` | 0.7.2 | 2025-03 | Django 4.2–5.2; DRF 3.14+; Py 3.9–3.13 | ACTIVE |
| `drf-extra-fields` | 3.7.0 | 2023-08 | Django ≤4.0; Python 3.7–3.11 | STALE |
| `djangorestframework-queryfields` | 1.1.0 | 2023-11 | README Django 1.7–3.2+ | STALE |
| `drf-flex-fields` | 1.0.2 | 2023-03 | Py classifiers stop at 3.7; no Django signal | STALE |
| `djangorestframework-serializer-extensions` | — | 2020-09 | — | ABANDONED |

Note: DRF's page links this last one as `django-rest-framework-serializer-extensions`, which 404s
on PyPI. The real distribution is `djangorestframework-serializer-extensions`.

## Async, errors, operations

| PyPI name | Version | Last release | Declared support | Status |
|---|---|---|---|---|
| `adrf` | 0.1.13 | 2026-06 | Python 3.8–3.14; docs require Django 4.1+ | ACTIVE |
| `drf-standardized-errors` | 0.16.0 | 2026-04 | README Django ≥3.2, DRF ≥3.12; Py 3.8–3.14 | ACTIVE |
| `drf-api-logger` | 1.4.0 | 2026-07 | Django 4.2–6.0; DRF ≥3.16; Py 3.10–3.13 | ACTIVE |
| `apitally` | 0.25.1 | 2026-06 | DRF ≥3.10; Py 3.10–3.14; SaaS backend required | ACTIVE |
| `drf-tweaks` | 0.10.0 | 2026-03 | — | ACTIVE — revived after a 4.5-year gap |
| `django-requestlogs` | 0.8.3 | 2025-03 | Django 1.11–5.0; Python 3.8–3.12 | ACTIVE |
| `djangorestframework-datatables` | 0.7.2 | 2024-06 | Django 3.2–5.0; DRF 3.14; Py 3.8–3.12 | STALE |
| `drf-haystack` | 1.9.1 | 2024-11 | Version-less classifiers | STALE |
| `django-elasticsearch-dsl-drf` | 0.22.5 | 2022-07 | Django 2.2–3.2; ES 6/7; Py ≤3.9 | ABANDONED |

## Renderers, parsers, cosmetics

| PyPI name | Version | Last release | Declared support | Status |
|---|---|---|---|---|
| `drf-redesign` | 0.6.0 | 2025-08 | Python 3.10–3.13 | ACTIVE |
| `drf-ujson2` | 1.8.0 | 2025-02 | Django 4.2–5.1; Python 3.10–3.13 | ACTIVE |
| `djangorestframework-csv` | 3.0.2 | 2023-12 | Python 3.8–3.11; tested Django ≤4.2 | STALE |
| `djangorestframework-rapidjson` | 0.2.0 | 2023-10 | Python 3.8–3.12; no version pins | STALE |
| `djangorestframework-camel-case` | 1.4.2 | 2023-02 | Python 3.6–3.10 | STALE |
| `djangorestframework-msgpack` | 1.0.2 | 2017-04 | No metadata | ABANDONED |

## Supporting packages not on DRF's page

| PyPI name | Version | Last release | Declared support | Status |
|---|---|---|---|---|
| `django-cors-headers` | 4.9.0 | 2025-09 | Django 4.2–6.0; Python 3.9–3.14 | ACTIVE |
| `django-storages` | 1.14.6 | 2025-04 | Django 3.2–5.1; Python 3.7–3.12 | ACTIVE |

## Confirmed abandoned

Every one of these is still linked from DRF's official Third Party Packages page.

| PyPI name | Version | Last release |
|---|---|---|
| `drf-any-permissions` | 0.0.1 | 2013-07 |
| `djangorestrelationalhyperlink` | 1.2.1 | 2013-08 |
| `djangorestframework-chain` | 0.1.3 | 2013-12 |
| `djangorestframework-digestauth` | 1.1.0 | 2014-01 |
| `djangorestframework-httpsignature` | 1.0.0 | 2015-05 |
| `djangorestframework-hstore` | 1.3 | 2015-06 |
| `rest-condition` | 1.0.3 | 2016-11 |
| `drf-url-filters` | 0.5.1 | 2017-06 |
| `djangorestframework-msgpack` | 1.0.2 | 2017-04 |
| `dry-rest-permissions` | 0.1.10 | 2018-01 |
| `hawkrest` | 1.0.1 | 2018-10 |
| `django-rest-multiple-models` | 2.1.3 | 2018-12 |
| `djangorestframework-composed-permissions` | 0.2.1 | 2019-03 |
| `drf-compound-fields` | 2.0.0 | 2019-09 |
| `django-rest-framework-mongoengine` | 3.4.1 | 2020-01 |
| `django-url-filter` | 0.3.15 | 2020-02 |
| `drf-typed-views` | 0.3.0 | 2020-06 |
| `djangorestframework-serializer-extensions` | — | 2020-09 |
| `drf-psq` | 1.1.0 | 2021-02 |
| `django-elasticsearch-dsl-drf` | 0.22.5 | 2022-07 |
| `drf-oidc-auth` | 3.0.0 | 2022-09 |
| `gaiarestframework` | — | 404 on PyPI |

## Corrections to DRF's page found during this check

- `django-rest-framework-httpsignature` — the linked name does not exist on PyPI; the real
  distribution is `djangorestframework-httpsignature` (abandoned, 2015-05).
- `gaiarestframework` — returns 404 on PyPI, its RSS feed, and the simple index.
- `django-rest-framework-serializer-extensions` — 404s; real name is
  `djangorestframework-serializer-extensions` (2020-09).
- `drf_tweaks` — was dormant from 2021 and revived with 0.10.0 in 2026-03. It is the one entry in
  the long-dormant group that is currently maintained.
