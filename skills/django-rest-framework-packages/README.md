# Django REST Framework third-party packages

A selection guide for DRF's third-party ecosystem: what to reach for when a DRF API needs a
capability the core doesn't ship, and what to avoid.

## What this skill covers

- **Need → package mapping** across authentication, permissions, OpenAPI schema, filtering,
  routing, serializers, async, error handling, logging, renderers, and search
- **Maintenance status** for the ~45 packages worth recommending, checked against PyPI on
  **2026-08-14** (latest version, last release date, declared Django/Python/DRF support)
- **An explicit "do not adopt" list** — 21 packages DRF's own page still recommends that have had
  no release since 2013–2022
- **The gaps in DRF's official list** — `drf-spectacular`, `django-filter`, `django-cors-headers`,
  `django-guardian`, and `drf-writable-nested` are among the most-used DRF packages in production
  and appear nowhere on it
- **Integration recipes** for the packages worth defaulting to

## Why it exists

DRF deliberately keeps a small core and pushes capability into third-party packages. Its
[Third Party Packages page](https://www.django-rest-framework.org/community/third-party-packages/)
is the canonical index — but it is append-only and unordered. Nothing on it is marked deprecated,
nothing is ranked, and a package last released in 2013 sits in the same bulleted list as one
released last month. An agent reading that page top-to-bottom will confidently recommend
`rest_condition` for permission composition, which has not shipped since 2016.

This skill is that page with maintenance status attached and a decision order in front of it.

## Sources

- [DRF Third Party Packages](https://www.django-rest-framework.org/community/third-party-packages/) — the full index (fetched 2026-08-14)
- [DRF API Guide](https://www.django-rest-framework.org/api-guide/requests/) — what's already in core, checked first
- [Django Packages DRF grid](https://www.djangopackages.com/grids/g/django-rest-framework/) — community usage signal
- PyPI project pages and release feeds — version, release date, and classifier data for the vetted set

## How to apply

1. **Check core DRF first.** Throttling, versioning, pagination, content negotiation, and token
   auth are built in. Don't add a dependency for something you already have.
2. **Consult the need → package table in `SKILL.md`.** Prefer ACTIVE over STALE, and never adopt
   from the abandoned list.
3. **Re-verify before installing.** Status data ages. `pip index versions <pkg>` or the PyPI
   project page gives you the current answer in seconds.
4. **When auditing an existing project**, diff its DRF-adjacent dependencies against the abandoned
   list and raise anything that matches as migration debt.

## Caveats

- Status labels are a snapshot from 2026-08-14. Re-check anything before adopting it.
- Classifier metadata lags reality in both directions. A missing `Framework :: Django :: 6.0`
  classifier is weak evidence; a *recent* release whose classifiers still cap at Django 3.2 is a
  much stronger signal that nobody has tested it lately.
- Packages in the long tail of `references/catalog.md` are marked `unvetted` — they are recorded
  for recognition (so an agent knows what a project's existing dependency does), not endorsed.
