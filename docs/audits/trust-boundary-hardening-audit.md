# Trust-boundary hardening audit

Audit date: 2026-08-20  
Audited commit: `d1c64eedef1793549af57cca61e87d7ba0d6b793` (`origin/main`)  
Working branch: `codex/hardening-trust-boundary-phase-1`

This audit treats the external review as a set of hypotheses. Classification reflects the code and
tests at the audited commit, not the review's wording. The only open pull request at audit time was
#109 (an unrelated Express overlay). Existing issues #73 and #74 overlap future hook portability and
mechanical evidence work; neither implements the Phase 1 controls below.

## Finding register

| ID | Finding | Status | Evidence | Existing tests | Planned action |
|----|---------|--------|----------|----------------|----------------|
| P0-1 | Gate override semantics permit prohibited waivers | **CONFIRMED** | `pipeline.close_gate()` applies `--force` to the combined Critical/High/Medium blocker set and writes `overridden`; CLI help advertises that bypass. | `test_close_gate_force_with_reason_records_override` positively asserts a High override succeeds. | Prohibit Critical/High waiver in the domain; add structured Medium `accepted-risk`; retain legacy `overridden` reading with a migration warning. |
| P0-2 | Any installed gate can be skipped | **CONFIRMED** | `pipeline.skip_gate()` checks only reason, gate membership, order, and aborted state. `ResolvedPlan` and the install snapshot have no gate requirement metadata. | `test_skip_gate_records_and_advances_position` positively skips required `build-green`. | Add one catalog-owned gate-definition map; allow only configured conditional gates to record structured `not-applicable` evidence. |
| P0-3 | A new run can begin at an arbitrary later gate | **CONFIRMED** | `_position()`/`_order_check()` deliberately allow any first entry; `close_gate()` and `skip_gate()` create a snapshot implicitly. | `test_close_gate_bootstrap_anchors_anywhere_then_enforces` and CLI tests assert the implicit bootstrap. | Add explicit start/adopt/resume/complete lifecycle, terminal states, run identity, and v1 compatibility handling. |
| P0-4 | Filesystem containment does not cover all writes | **CONFIRMED** | `scaffold.py`, `upgrader.py`, and `pipeline.py` perform direct `mkdir`, `write_text`, `copy2`, `move`, `unlink`, `rmtree`, and `os.replace` operations. `_inside()` protects only upgrade-orphan deletion. | Existing containment tests cover hostile manifest text/deletion, not add/update/backup/sidecar/config/runtime writes. | Route project mutations through a centralized secure filesystem layer with ancestry/link/reparse checks immediately before mutation. |
| P0-5 | Strict schema validation can silently skip | **CONFIRMED** | `jsonschema` is optional; `_strict_schema_artifact()` returns silently; `_check_catalog_schemas()` emits `OK ... skipped`. Future format versions are generally accepted or warned. | Two tests explicitly require strict success without `jsonschema`; schema tests cover only selected malformed artifacts. | Make `jsonschema` a runtime dependency, fail strict calls closed if unavailable, version current artifacts, and reject unknown future versions. |
| P0-6 | Release publication does not promote the artifact tested by CI | **CONFIRMED** | CI build, CI wheel-smoke, and publish each rebuild independently; publish does not depend on CI and lacks digest comparison, robust PyPI status handling, concurrency, SHA pins, provenance verification, or attached release assets. | Static workflow evaluation currently permits mutable action refs and does not assert artifact identity. | Build once, smoke/promote the same artifact, publish without rebuilding, attest it, verify PyPI digests, attach it to the release, and document recovery/settings. |
| P0-7 | Official Claude Code conformance is not enforced | **CONFIRMED** | CI never runs `claude plugin validate`; no compatibility catalog exists; `doctor()` does not inspect Claude Code; `KNOWN_EVENTS` rejects current official events. | Plugin tests duplicate the stale event set. Local `claude plugin validate . --strict` passed with Claude Code 2.1.178. | Add versioned compatibility data, official-validation CI, doctor reporting, and forward-compatible event recognition. |
| P0-8 | First/force installation is not transactional | **CONFIRMED** | `install_sdlc()` mutates the live tree step-by-step; missing selected components are logged as skipped; only upgrade writes a journal. | Current install/merge tests cover normal convergence and user preservation, not rollback after injected stage failures. | Preflight every component, render/validate in staging, journal the live apply, roll back failures, and make interrupted install visible/convergent. |

## Source-backed evidence

### P0-1 — prohibited gate overrides

- Policy: `rules/quality-gates.md` says only residual Medium risk may be accepted and Critical/High
  are never waivable.
- Domain: `src/claude_kit/pipeline.py::_blocking_findings()` combines all three blocking severities;
  `close_gate()` lets `force=True` plus a free-form reason bypass the whole map.
- Surface: `src/claude_kit/cli.py::pipeline_close_gate()` describes `--force` as closing despite
  Critical/High/Medium findings and forwards it unchanged.
- Validation: `pipeline.validate()` warns about `overridden` but returns success.
- Reproduction: a snapshot with an open Critical finding was force-closed and persisted with
  `status: overridden`.

### P0-2 — required gates can be skipped

- `catalog/profiles.yaml` stores only ordered gate names. Conditionality exists in comments/prose.
- `src/claude_kit/models.py::ResolvedPlan` exposes only `gates: list[str]`.
- `src/claude_kit/scaffold.py::_write_config()` persists only that list.
- `src/claude_kit/pipeline.py::skip_gate()` has no required/conditional lookup, condition identifier,
  evidence, or commit binding.
- Reproduction: `build-green` was recorded `skipped` successfully.

### P0-3 — implicit run creation and adoption

- `src/claude_kit/pipeline.py::_position()` documents that the first record may anchor anywhere.
- `_order_check()` accepts any gate when there is no anchor.
- `close_gate()` and `skip_gate()` synthesize a schema-1 snapshot when none exists.
- `rules/continuity.md` explicitly describes this implicit mid-flight adoption.
- Strict validation only warns on an unknown future runtime schema.

### P0-4 — incomplete write containment

Adversarial probes against the audited code all returned success while mutating an external victim:

- fresh install through a symlinked `.claude/`;
- pipeline snapshot creation through a symlinked `.claude/state/`;
- a symlinked `CLAUDE.md.claude-kit` sidecar;
- upgrade add through a symlinked `.claude/agents/`.

`models.contained_relpath()` rejects textual traversal in manifest entries and
`upgrader._inside()` checks orphan deletion, but neither protects add/update/backup/sidecar/config,
installer, or runtime-state writes at mutation time. `pathlib.resolve()` at command entry does not
close the time-of-check/time-of-use gap.

### P0-5 — fail-open strict validation

- `pyproject.toml` places `jsonschema` in an optional extra.
- `src/claude_kit/schemas.py` documents missing support as a no-op.
- `validator._strict_schema_artifact()` silently returns when unavailable.
- `validator._check_catalog_schemas()` reports skipped checks as `OK` and recommends the wrong
  distribution spelling (`claude-kit[schema]`).
- `pipeline.validate(strict=True)` warns rather than fails for a future schema.
- `InitOptions.from_dict()` and `UpgradeJournal.from_dict()` accept arbitrary future versions;
  the stack snapshot has no version.

Positive control: schemas declare JSON Schema 2020-12, and `validator_for()` plus `check_schema()`
does validate each schema against its declared metaschema when the dependency is present.

### P0-6 — rebuild instead of promote

- `.github/workflows/ci.yml`: `build` creates wheel+sdist; `wheel-smoke` builds a different wheel.
- `.github/workflows/publish.yml`: a separate push-triggered workflow builds a third set, without a
  dependency on CI completion.
- The PyPI probe treats every non-200 response as absence, uses no retry/timeout, and publication
  uses `skip-existing` instead of detecting a race/digest mismatch.
- Actions use mutable tags/branches. There is no SHA manifest, artifact attestation, post-publish
  digest check, or GitHub Release asset upload.
- Missing changelog content degrades to generic notes instead of failing.

Repository settings verified through the GitHub API at audit time: `main` was protected with one
approval, CODEOWNERS review, signed commits, and force-push/deletion blocking; required status checks
and administrator enforcement were disabled; no ruleset existed; the `pypi` environment had no
protection rules and allowed administrator bypass. Secret scanning and push protection were enabled.
Those observations are not claims that the missing settings were changed.

### P0-7 — missing official compatibility boundary

- No workflow provisions Claude Code or runs `claude plugin validate . --strict`.
- `validator.doctor()` does not inspect the installed Claude Code version.
- `validator.KNOWN_EVENTS` contains only nine older events and reports newer valid events as ones that
  “will never fire”; `PermissionRequest` reproduced the false rejection.
- Local evidence: Claude Code 2.1.178 validated this plugin successfully. That proves one observed
  version only, not a supported-version matrix.

### P0-8 — non-transactional installation

- `scaffold.install_sdlc()` writes rules, root docs, agents, skills, hooks/settings, MCP files,
  runtime directories, gitignore, and config directly into the live project in sequence.
- `_install_agents()`, `_install_skills()`, overlay/org installers, and hook/script installation skip
  missing selected payload components instead of failing preflight.
- Reproduction: an injected failure after the rules step left live rules and `CLAUDE.md` without a
  manifest or install journal. A deliberately missing selected agent was logged as skipped while the
  stack snapshot still claimed it.
- Upgrade has a visibility journal and convergent replay, but it is not rollback-transactional; merge
  install does not journal at all.

## Untouched baseline

- `pytest -q`: **1283 passed in 210.24s**.
- Ruff check: passed; Ruff format check: 103 files already formatted.
- mypy: passed for 19 source files.
- shellcheck (`-S warning`): passed.
- Hook drift, docs consistency, strict cross-references, skill-description cap, rule-size check, and
  MCP pin check: passed.
- Isolated package build: wheel and sdist built after allowing the build environment to download
  Hatchling; Twine checks passed.
- `claude plugin validate . --strict`: passed locally with Claude Code 2.1.178.
- `actionlint` and `zizmor`: unavailable locally at audit time; they were not reported as passed.

