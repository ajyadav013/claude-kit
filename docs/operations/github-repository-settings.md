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

## `protected-host-behavior` environment

- Create an environment named exactly `protected-host-behavior`. Require reviewers, prevent
  self-review, disable administrator bypass, and restrict deployment to the default branch. The
  workflow also checks the ref itself; the environment is the credential boundary that YAML alone
  cannot supply.
- Add at least one independent trusted collaborator or organization team as the required reviewer
  before the first run. A repository with only the workflow actor as a collaborator cannot combine
  required approval with prevent-self-review; the actor must never approve their own protected
  deployment.
- Add `CKIT_ANTHROPIC_API_KEY` and `CKIT_OPENAI_API_KEY` as environment secrets. Do not define them
  as repository, organization, or job-level environment variables. The protected workflow passes
  the Anthropic key only into an out-of-workspace Claude `apiKeyHelper` staging step. The OpenAI key
  has exactly two protected channels: the exact-wheel coordinator's pinned passive managed Codex
  host process and the pinned official `openai/codex-action` proxy. Both are read-only/no-shell
  probes; neither makes the key available to project tools or persists it in the fixture.
- Keep `.github/workflows/protected-host-behavior.yml` limited to `schedule` and
  `workflow_dispatch`. Never add `pull_request`, `pull_request_target`, or an unreviewed branch
  trigger to a workflow that can access these secrets.
- Review all four minimum/current × Claude-to-Codex/Codex-to-Claude matrix cells and their
  protected artifacts after each run. A missing secret, non-default ref, duplicate `SessionStart`,
  credential-bearing hook environment, native
  mutation outside coordinator-owned pipeline state/evidence, generated `protect-secrets` bypass,
  or mismatched observation receipt must fail closed. Codex runs with the built-in read-only
  permission profile and an isolated home whose trust table names only the canonical prepared
  project path. The official action rejects hook-trust bypasses under protected profiles, so the
  workflow instead stages a byte-identical copy of the exact prepared `.codex/hooks.json` as
  root-owned `/etc/codex/hooks.json`; Codex treats system hooks as managed policy. The staging step
  refuses a pre-existing `/etc/codex`, verifies source/destination hashes plus ownership and modes,
  and runs immediately before the action removes sudo. Ordinary CI and user workflows must never
  install this fixture-specific system policy. The verifier control and receipts contain
  commitments, not plaintext discovery values or the blocked canary; the guard evidence records
  only the exact scaffolded command digest, provider-native disposition metadata, and output
  hashes. A configured workflow is not promotion evidence until all four matrix cells are green.

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

After the protected workflow and reviewed implementation are on `main`, dispatch and retain the
behavioral proof without invoking the release workflow:

```bash
protected_main_sha="$(gh api repos/{owner}/{repo}/commits/main --jq .sha)"
protected_run_url="$(
  gh workflow run protected-host-behavior.yml --ref main |
    awk '/^https:\/\/github\.com\// { url=$0 } END { print url }'
)"
protected_run_id="${protected_run_url##*/}"
case "$protected_run_id" in
  ""|*[!0-9]*) echo "GitHub did not return the dispatched run URL" >&2; exit 1 ;;
esac
test "$(gh run view "$protected_run_id" --json event --jq .event)" = workflow_dispatch
test "$(gh run view "$protected_run_id" --json headBranch --jq .headBranch)" = main
test "$(gh run view "$protected_run_id" --json headSha --jq .headSha)" = "$protected_main_sha"
gh run watch "$protected_run_id" --exit-status
gh run view "$protected_run_id" --json jobs --jq '.jobs[] | [.name, .conclusion] | @tsv'
gh run download "$protected_run_id" --dir "protected-host-receipts/$protected_run_id"
```

An independent required reviewer must approve the pending `protected-host-behavior` deployment in
GitHub. Require a green `Read protected host matrix` job plus green conclusions for exactly these
four jobs:

- `protected-host-behavior-minimum-claude-codex`
- `protected-host-behavior-minimum-codex-claude`
- `protected-host-behavior-current-claude-codex`
- `protected-host-behavior-current-codex-claude`

Download and inspect all four direction-scoped artifacts before their 14-day retention expires.
Missing approval, a missing job or artifact, or any non-green conclusion leaves Codex and `both` in
Preview.

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
| `openai/codex-action` | `v1` | `86365089eb2b84e0a8fb0717b304f8bdcb13b20e` |

Dependabot may propose newer commits, but reviewers must resolve the advertised tag themselves and
update this ledger with the audit date. A moving tag or branch is evidence metadata, never the value
used in `uses:` or the actionlint install command.
