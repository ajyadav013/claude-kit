# GitHub repository settings required for releases

Workflow YAML cannot enforce repository and environment controls. Configure these settings in the
GitHub UI (or an organization ruleset) and review them after ownership or release-process changes.

## `main` protection

- Require a pull request, at least one approving review, CODEOWNERS review, dismissal of stale
  approvals, and approval of the latest push.
- Require the current CI job set before merge. At minimum require every Python test lane, lint,
  shellcheck, static catalog/schema checks, workflow security, official Claude Code minimum/current
  validation, build, and exact-wheel smoke. Do not rely only on the aggregate workflow conclusion.
- Require branches to be up to date with `main` before merging.
- Require signed commits, linear history, conversation resolution, and enforcement for administrators.
- Block force pushes, branch deletion, and direct pushes. Prefer a ruleset scoped to the default
  branch so bypass actors are explicit and audited.

## Release-tag protection

- Add a tag ruleset for `v*` that restricts creation to the verified release workflow, blocks
  updates and deletion, and grants no routine bypass. Emergency recovery must be explicit, audited,
  and follow the release-recovery runbook; never move a published version tag to another commit.
- Require the tag target to be the authenticated successful `main` CI SHA. The workflow checks this
  itself, while the ruleset prevents an actor from replacing the tag after that check.

## `pypi` environment

- Protect the environment with required reviewers who are not the release author, prevent
  self-review, restrict deployment to `main`, and disable administrator bypass.
- Configure the PyPI trusted publisher for owner `ajyadav013`, repository `claude-kit`, workflow
  `.github/workflows/publish.yml`, and environment `pypi`. No long-lived PyPI token is needed.
- Keep default `GITHUB_TOKEN` permissions read-only. The workflow grants `id-token: write` only to
  attestation/publish jobs, `attestations: write` only to provenance generation, and `contents: write`
  only to the post-PyPI GitHub Release job.

## Repository security

- Enable secret scanning, push protection, Dependabot alerts, dependency graph, and Dependabot
  security updates. The checked-in Dependabot config covers GitHub Actions and Python dependencies;
  action update PRs must retain full 40-character commit pins.
- Enable private-vulnerability reporting and require 2FA for collaborators. Review deploy keys,
  GitHub Apps, Actions allow-lists, ruleset bypass actors, and environment reviewers quarterly.

## Verification checklist

After changing settings, open a harmless PR and confirm every required check appears. Then use a
non-publishing CI run to confirm `verified-dist` contains exactly one wheel, one sdist,
`SHA256SUMS`, and release notes. Do not weaken protection to make a release pass; use the recovery
procedure instead.

The audit-time observed settings and their missing controls are recorded in
[`docs/audits/trust-boundary-hardening-audit.md`](../audits/trust-boundary-hardening-audit.md).
This file is a required-state runbook, not a claim that those manual settings were changed.

## Supply-chain pin ledger (audited 2026-08-20)

The executable refs were resolved directly with `git ls-remote` against each upstream repository;
the workflows execute the 40-character commit, while comments retain the human-readable ref.

| Component | Audited upstream ref | Commit |
|---|---|---|
| `actions/checkout` | `v7` | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-python` | `v7` | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| `actions/setup-node` | `v6` | `249970729cb0ef3589644e2896645e5dc5ba9c38` |
| `actions/upload-artifact` | `v7` | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |
| `actions/download-artifact` | `v8` | `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` |
| `actions/attest-build-provenance` | `v3` | `43d14bc2b83dec42d39ecae14e916627a18bb661` |
| `actions/github-script` | `v9` | `373c709c69115d41ff229c7e5df9f8788daa9553` |
| `pypa/gh-action-pypi-publish` | `release/v1` | `dc37677b2e1c63e2034f94d8a5b11f265b73ba33` |
| `rhysd/actionlint` | `v1.7.12` | `914e7df21a07ef503a81201c76d2b11c789d3fca` |

Dependabot may propose newer commits, but reviewers must resolve the advertised tag themselves and
update this ledger with the audit date. A moving tag or branch is evidence metadata, never the value
used in `uses:` or the actionlint install command.
