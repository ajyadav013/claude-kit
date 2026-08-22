# Release Policy

This document describes claude-kit's versioning, release, and support policy.

## Versioning

claude-kit follows [Semantic Versioning](https://semver.org/) (SemVer).

**Pre-1.0 stability:** The project is currently pre-1.0 (Development Status :: 4 - Beta). During
the 0.x phase, minor version increments (e.g., 0.56.0 → 0.57.0) may introduce behavior changes or
breaking changes. Breaking changes are always called out explicitly in the CHANGELOG.

Once the project reaches 1.0.0, the standard SemVer contract will apply: breaking changes only in
major versions, backwards-compatible features in minor versions, and fixes in patch versions.

## Supported Versions

**Only the latest released version receives fixes.** There is no long-term-support (LTS) branch or
backport policy. When a new version is released, the previous version is no longer supported.

This policy mirrors the project's [SECURITY.md](../SECURITY.md) stance: security fixes are
published only for the latest release.

## What Is in a Release

Every release includes:

- A version bump in the three manually maintained version declarations (enforced by CI):
  - `pyproject.toml`
  - `src/claude_kit/__init__.py` (`__version__`)
  - `SECURITY.md` (the "Supported Versions" table)
- Regenerated Claude Code and Codex plugin manifests from `catalog/plugin-metadata.yaml` via
  `scripts/gen_provider_manifests.py` (their version comes from `pyproject.toml`; the native Codex
  marketplace format has no version field)
- A new section in `CHANGELOG.md` following [Keep a Changelog](https://keepachangelog.com/)
  format, with a dated heading matching the new version
- A "Not adopted (deliberately)" note in the CHANGELOG entry, documenting what was reviewed but
  intentionally excluded from the kit

CI runs `scripts/gen_provider_manifests.py --check` to reject generated-file drift, while
`scripts/check_docs_consistency.py` enforces version parity across the manual declarations,
versioned provider outputs, and latest CHANGELOG heading.

## Release Process

1. **Bump the version** in the three manual declarations listed above, then regenerate provider
   manifests with `python scripts/gen_provider_manifests.py`.
2. **Update CHANGELOG.md** with a new section for the release, including the date and the
   "Not adopted" note.
3. **Merge to main.** Once the pull request is merged:
   - `.github/workflows/publish.yml` automatically checks whether the version in `pyproject.toml`
     is newer than the latest version on PyPI.
   - If the version is new, the workflow publishes the package to PyPI and creates:
     - A git tag `vX.Y.Z`
     - A GitHub Release whose body is the new version's CHANGELOG section

No manual PyPI upload or tag creation is required. As of version 0.57.0, the workflow handles both
PyPI publishing and GitHub Release creation in a single run.

## Publishing and Provenance

Releases are published to [PyPI](https://pypi.org/project/claude-code-kit/) via **OIDC Trusted
Publishing** (no long-lived token) with **PEP 740 build attestations** for provenance verification.

The workflow is version-gated: it only publishes when the version in `pyproject.toml` is newer than
the latest version on PyPI.

## Pre-1.0 Stability Caveat

Because the project is pre-1.0, minor version updates may include:

- Changes to the SDLC agent protocols or quality gates
- Modifications to the catalog schema or resolution behavior
- Removal or renaming of skills, agents, or rules
- Breaking changes to the CLI interface

Always review the CHANGELOG before upgrading. Breaking changes are explicitly called out.

## Release Cadence

Releases are shipped **when ready**. There is no fixed calendar schedule.

Many minor releases are driven by **reuse-first adoption reviews** — surveys of external projects
or organizations (e.g., Alibaba, Microsoft, Google) that result in new overlay rules, skills, or
agents being added to the kit.

## Reporting Issues

- **Feature requests and regressions:** Open a [GitHub issue](https://github.com/ajyadav013/claude-kit/issues).
- **Security vulnerabilities:** Follow the [SECURITY.md](../SECURITY.md) policy (private reporting via GitHub).

---

**License:** MIT © Arjunsingh Yadav  
**Repository:** [github.com/ajyadav013/claude-kit](https://github.com/ajyadav013/claude-kit)
