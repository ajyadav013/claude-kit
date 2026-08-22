# Complete catalog

Every package listed on DRF's [Third Party Packages page](https://www.django-rest-framework.org/community/third-party-packages/)
(fetched 2026-08-14), in DRF's own categories and order, plus a final section for the widely-used
packages that page omits.

Status: **ACTIVE** / **STALE** / **ABANDONED** for the vetted set; **unvetted** means it was
recorded for recognition but not checked against PyPI. An unvetted entry is not an endorsement —
verify before adopting. See `maintenance-status.md` for the vetting data.

## Async Support

| Package | Purpose | Status |
|---|---|---|
| [adrf](https://github.com/em1208/adrf) | Async views, viewsets, and serializers for DRF | ACTIVE |

## Authentication

| Package | Purpose | Status |
|---|---|---|
| [djangorestframework-simplejwt](https://github.com/davesque/django-rest-framework-simplejwt) | JSON Web Token authentication | ACTIVE |
| [django-oauth-toolkit](https://github.com/evonove/django-oauth-toolkit) | OAuth 2.0 provider | ACTIVE |
| [djoser](https://github.com/sunscrapers/djoser) | Views for registration, login, logout, password reset, activation | ACTIVE |
| [dj-rest-auth](https://github.com/iMerica/dj-rest-auth) | REST endpoints for registration, auth (incl. social), password reset, user details | ACTIVE |
| [DRF Auth Kit](https://github.com/huynguyengl99/drf-auth-kit) | Full REST auth: JWT cookies, social login, MFA, user management, typed OpenAPI schema | ACTIVE |
| [django_pyoidc](https://github.com/makinacorpus/django_pyoidc) | OpenID Connect (OIDC) authentication | ACTIVE |
| [drfpasswordless](https://github.com/aaronn/django-rest-framework-passwordless) | Passwordless login/signup via email or mobile | STALE |
| [drf-oidc-auth](https://github.com/ByteInternet/drf-oidc-auth) | OpenID Connect token authentication | ABANDONED (2022-09) |
| [hawkrest](https://github.com/kumar303/hawkrest) | Hawk HTTP Authorization | ABANDONED (2018-10) |
| [djangorestframework-httpsignature](https://github.com/etoccalino/django-rest-framework-httpsignature) | HTTP Signature authentication | ABANDONED (2015-05) |
| [djangorestframework-digestauth](https://github.com/juanriaza/django-rest-framework-digestauth) | Digest Access Authentication | ABANDONED (2014-01) |
| [django-rest-authemail](https://github.com/celiao/django-rest-authemail) | RESTful signup and auth using email addresses | unvetted |

## Permissions

| Package | Purpose | Status |
|---|---|---|
| [drf-access-policy](https://github.com/rsinger86/drf-access-policy) | Declarative permissions inspired by AWS IAM policies | STALE |
| [drf-psq](https://github.com/drf-psq/drf-psq) | Action-based `permission_classes`, `serializer_class`, `queryset` | ABANDONED (2021-02) |
| [dry-rest-permissions](https://github.com/FJNR-inc/dry-rest-permissions) | Per-action permission definitions | ABANDONED (2018-01) |
| [djangorestframework-composed-permissions](https://github.com/niwibe/djangorestframework-composed-permissions) | Composing complex permissions | ABANDONED (2019-03) |
| [rest_condition](https://github.com/caxap/rest_condition) | Building complex permissions | ABANDONED (2016-11) |
| [drf-any-permissions](https://github.com/kevin-brown/drf-any-permissions) | Alternative permission handling | ABANDONED (2013-07) |
| [axioms-drf-py](https://github.com/abhishektiwari/axioms-drf-py) | Claim-based fine-grained authorization (scopes, roles, groups) via OAuth2/OIDC JWTs | unvetted |

DRF core has supported `&` / `|` / `~` operators on permission classes since 3.9 — most of what
these packages existed for is now built in.

## Serializers

| Package | Purpose | Status |
|---|---|---|
| [djangorestframework-gis](https://github.com/djangonauts/django-rest-framework-gis) | Geographic / GeoJSON add-ons | ACTIVE |
| [djangorestframework-jsonapi](https://github.com/django-json-api/django-rest-framework-json-api) | jsonapi.org-compliant parser, renderer, serializers | ACTIVE |
| [django-pydantic-field](https://github.com/surenkov/django-pydantic-field) | Pydantic models as schemas for Django `JSONField`, with DRF integration | ACTIVE |
| [drf-pydantic](https://github.com/georgebv/drf-pydantic) | Use Pydantic for DRF validation and (de)serialization | ACTIVE |
| [django-restql](https://github.com/yezyilomo/django-restql) | GraphQL-like field selection, nested read and write | ACTIVE |
| [djangorestframework-dataclasses](https://github.com/oxan/djangorestframework-dataclasses) | Automatic field generation for Python dataclasses | ACTIVE |
| [djangorestframework-queryfields](https://github.com/wimglenn/djangorestframework-queryfields) | Client-controlled response fields | STALE |
| [drf-flex-fields](https://github.com/rsinger86/drf-flex-fields) | Dynamic field expansion and sparse fieldsets via URL params | STALE |
| [djangorestframework-serializer-extensions](https://github.com/evenicoulddoit/django-rest-framework-serializer-extensions) | Black/whitelist fields, conditional child-serializer expansion | ABANDONED (2020-09) |
| [django-rest-framework-mongoengine](https://github.com/umutbozkurt/django-rest-framework-mongoengine) | MongoDB as the storage layer | ABANDONED (2020-01) |
| [djangorestframework-hstore](https://github.com/djangonauts/django-rest-framework-hstore) | django-hstore `DictionaryField` support | ABANDONED (2015-06) |
| [html-json-forms](https://github.com/wq/html-json-forms) | HTML JSON Form submission processing | unvetted |
| [drf-action-serializer](https://github.com/gregschmit/drf-action-serializer) | Per-action field config for viewsets | unvetted |
| [graphwrap](https://github.com/PaulGilmartin/graph_wrap) | Turn a REST API into a GraphQL API via Graphene-Django | unvetted |
| [drf-shapeless-serializers](https://github.com/khaledsukkar2/drf-shapeless-serializers) | Assemble and configure serializers at runtime | unvetted |

## Serializer fields

| Package | Purpose | Status |
|---|---|---|
| [drf-extra-fields](https://github.com/Hipo/drf-extra-fields) | Extra serializer fields (base64 file/image, points, ranges) | STALE |
| [drf-compound-fields](https://github.com/estebistec/drf-compound-fields) | Compound fields such as lists of simple values | ABANDONED (2019-09) |
| [django-versatileimagefield](https://github.com/WGBH/django-versatileimagefield) | `ImageField` replacement serving multiple renditions from one field | unvetted |

## Views

| Package | Purpose | Status |
|---|---|---|
| [django-rest-multiple-models](https://github.com/MattBroach/DjangoRestMultipleModels) | Serve multiple models/querysets from one request | ABANDONED (2018-12) |
| [drf-typed-views](https://github.com/rsinger86/drf-typed-views) | Type annotations to validate/deserialize request params | ABANDONED (2020-06) |
| [rest-framework-actions](https://github.com/AlexisMunera98/rest-framework-actions) | Per-action control in viewsets | unvetted |

## Routers

| Package | Purpose | Status |
|---|---|---|
| [drf-nested-routers](https://github.com/alanjds/drf-nested-routers) | Routers and relationship fields for nested resources | ACTIVE |
| [wq.db.rest](https://wq.io/docs/about-rest) | Admin-style model registration with default URLs and viewsets | unvetted |

## Parsers

| Package | Purpose | Status |
|---|---|---|
| [djangorestframework-jsonapi](https://github.com/django-json-api/django-rest-framework-json-api) | jsonapi.org parser | ACTIVE |
| [djangorestframework-camel-case](https://github.com/vbabiy/djangorestframework-camel-case) | camelCase JSON renderer and parser | STALE |
| [djangorestframework-msgpack](https://github.com/juanriaza/django-rest-framework-msgpack) | MessagePack renderer and parser | ABANDONED (2017-04) |
| [nested-multipart-parser](https://github.com/remigermain/nested-multipart-parser) | Nested parser for multipart requests | unvetted |

## Renderers

| Package | Purpose | Status |
|---|---|---|
| [drf_ujson2](https://github.com/Amertz08/drf_ujson2) | JSON rendering via UJSON | ACTIVE |
| [djangorestframework-csv](https://github.com/mjumbewu/django-rest-framework-csv) | CSV renderer | STALE |
| [djangorestframework-rapidjson](https://github.com/allisson/django-rest-framework-rapidjson) | rapidjson parser and renderer | STALE |
| [rest-pandas](https://github.com/wq/django-rest-pandas) | pandas DataFrame renderers: Excel, CSV, SVG | unvetted |

## Filtering

| Package | Purpose | Status |
|---|---|---|
| [django-rest-framework-guardian](https://github.com/rpkilby/django-rest-framework-guardian) | django-guardian integration, incl. `DjangoObjectPermissionsFilter` (removed from DRF core) | ACTIVE |
| [django-url-filter](https://github.com/miki725/django-url-filter) | Filter data via human-friendly URLs | ABANDONED (2020-02) |
| [drf-url-filter](https://github.com/manjitkumar/drf-url-filters) | Configurable filters on `ModelViewSet` querysets with query-param validation | ABANDONED (2017-06) |
| [djangorestframework-chain](https://github.com/philipn/django-rest-framework-chain) | Arbitrary chaining of relations and lookup filters | ABANDONED (2013-12) |

Use `django-filter` (below) for query-param filtering. It is not on DRF's page but is the package
DRF's own [Filtering guide](https://www.django-rest-framework.org/api-guide/filtering/) documents.

## Misc

| Package | Purpose | Status |
|---|---|---|
| [drf-api-logger](https://github.com/vishalanandl177/DRF-API-Logger) | Configurable request/response logging, data masking, profiling, admin views | ACTIVE |
| [drf-standardized-errors](https://github.com/ghazi-git/drf-standardized-errors) | Exception handler standardizing error responses across all endpoints | ACTIVE |
| [apitally](https://github.com/apitally/apitally-py) | API monitoring, analytics, request logging middleware (SaaS backend) | ACTIVE |
| [drf-extensions](https://github.com/chibisov/drf-extensions) | Collection of extensions: caching, bulk routes, nested viewsets | ACTIVE |
| [drf_tweaks](https://github.com/ArabellaTech/drf_tweaks) | One-step validation serializers, count-less pagination, other tweaks | ACTIVE (revived 2026-03) |
| [django-requestlogs](https://github.com/Raekkeri/django-requestlogs) | Middleware and helpers for audit logging | ACTIVE |
| [drf-haystack](https://drf-haystack.readthedocs.io/en/latest/) | Haystack search integration | STALE |
| [djangorestframework-datatables](https://github.com/izimobil/django-rest-framework-datatables) | Server-side integration with Datatables | STALE |
| [django-elasticsearch-dsl-drf](https://github.com/barseghyanartur/django-elasticsearch-dsl-drf) | Elasticsearch DSL views, serializers, filter backends, pagination | ABANDONED (2022-07) |
| [djangorestrelationalhyperlink](https://github.com/fredkingham/django_rest_model_hyperlink_serializers_project) | Hyperlinked serializer that alters relationships via hyperlinks | ABANDONED (2013-08) |
| [gaiarestframework](https://github.com/AppsFuel/gaiarestframework) | Assorted DRF utilities | ABANDONED (404 on PyPI) |
| [drf-sendables](https://github.com/amikrop/drf-sendables) | User messages | unvetted |
| [cookiecutter-django-rest](https://github.com/agconti/cookiecutter-django-rest) | Cookiecutter template for a DRF API project | unvetted |
| [django-rest-framework-proxy](https://github.com/eofs/django-rest-framework-proxy) | Proxy requests to another API server | unvetted |
| [ember-django-adapter](https://github.com/dustinfarris/ember-django-adapter) | Ember.js adapter | unvetted |
| [drf-api-tracking](https://github.com/lingster/drf-api-tracking) | Track requests to DRF views | unvetted |
| [django-rest-framework-braces](https://github.com/dealertrack/django-rest-framework-braces) | `FormSerializer` / `SerializerForm` adapters between DRF and Django forms | unvetted |
| [django-rest-framework-version-transforms](https://github.com/mrhwick/django-rest-framework-version-transforms) | Delta transformations for resource versioning | unvetted |
| [django-rest-messaging](https://github.com/raphaelgyory/django-rest-messaging) (+ `-centrifugo`, `-js`) | Real-time pluggable messaging service | unvetted |
| [djangorest-alchemy](https://github.com/dealertrack/djangorest-alchemy) | SQLAlchemy support | unvetted |
| [django-rest-witchcraft](https://github.com/shosca/django-rest-witchcraft) | SQLAlchemy model serializers and viewsets | unvetted |
| [django-rest-framework-condition](https://github.com/jozo/django-rest-framework-condition) | ETag / Last-Modified cache-header decorators | unvetted |
| [djangorestframework-mvt](https://github.com/corteva/djangorestframework-mvt) | Serve Postgres data as Mapbox Vector Tiles | unvetted |
| [drf-viewset-profiler](https://github.com/fvlima/drf-viewset-profiler) | Line-by-line profiling of viewset methods | unvetted |
| [djangorestframework-features](https://github.com/cloudcode-hungary/django-rest-framework-features/) | Schema generation based on named features | unvetted |
| [django-lisan](https://github.com/Nabute/django-lisan) | Translation and localization for DRF APIs | unvetted |
| [django-api-client](https://github.com/rhenter/django-api-client) | DRF client grouping endpoint responses for use in CBVs/FBVs | unvetted |
| [fast-drf](https://github.com/iashraful/fast-drf) | Model-based library for faster API development | unvetted |
| [drf-api-action](https://github.com/Ori-Roza/drf-api-action) | Use DRF actions as library functions | unvetted |
| [wireup](https://github.com/maldoinc/wireup) | Dependency injection container with Django integration | unvetted |
| [django-versatileimagefield](https://github.com/WGBH/django-versatileimagefield) | Multi-rendition `ImageField` replacement | unvetted |

## Customization (browsable API)

| Package | Purpose | Status |
|---|---|---|
| [drf-redesign](https://github.com/youzarsiph/drf-redesign) | Bootstrap 5 restyle of the browsable API | ACTIVE |
| [drf-restwind](https://github.com/youzarsiph/drf-restwind) | TailwindCSS + DaisyUI restyle | unvetted |
| [drf-material](https://github.com/youzarsiph/drf-material) | Material Design restyle | unvetted |

Cosmetic only. Most production APIs disable `BrowsableAPIRenderer` outside development.

## Not on DRF's page, but standard in production

DRF's Third Party Packages index omits these. Several are documented elsewhere in DRF's own API
Guide; the rest are Django-level packages any real API needs. An agent working only from the
official list has no answer for "generate an OpenAPI schema" or "let my SPA call this API".

| Package | Purpose | Status | Where DRF documents it |
|---|---|---|---|
| [drf-spectacular](https://github.com/tfranzel/drf-spectacular) | OpenAPI 3 schema, Swagger/Redoc UI, typed client generation | ACTIVE | [Schemas](https://www.django-rest-framework.org/api-guide/schemas/) |
| [django-filter](https://github.com/carltongibson/django-filter) | Query-param filtering via `DjangoFilterBackend` | ACTIVE | [Filtering](https://www.django-rest-framework.org/api-guide/filtering/) |
| [drf-yasg](https://github.com/axnsan12/drf-yasg) | Swagger 2.0 schema generation (legacy) | ACTIVE | — |
| [django-cors-headers](https://github.com/adamchainz/django-cors-headers) | CORS headers for browser clients | ACTIVE | [AJAX, CSRF & CORS](https://www.django-rest-framework.org/topics/ajax-csrf-cors/) |
| [django-guardian](https://github.com/django-guardian/django-guardian) | Object-level permission backend | ACTIVE | [Permissions](https://www.django-rest-framework.org/api-guide/permissions/) |
| [drf-writable-nested](https://github.com/beda-software/drf-writable-nested) | Writable nested serializers | ACTIVE | — |
| [django-storages](https://github.com/jschneier/django-storages) | S3 / GCS / Azure media and static backends | ACTIVE | — |
