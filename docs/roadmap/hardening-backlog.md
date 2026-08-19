# Trust-boundary hardening backlog

These are issue drafts, not commitments in the Phase 1 implementation. Each draft is intentionally
bounded so it can become a standalone issue/PR. Existing issues are linked where one already owns the
topic; this file expands their acceptance criteria rather than creating a competing design.

## A. Parse mechanical evidence with registered adapters

**Rationale.** The pipeline can hash an artifact, but a hash proves identity rather than test meaning.
Calling evidence mechanical requires a parser that understands the producer's format and result.
This expands issue #74.

**Proposed design.** Add an `EvidenceParser` protocol and a versioned registry. Implement adapters for
JUnit XML, pytest reports, coverage.py JSON, LCOV, Cobertura, SARIF, Ruff JSON, mypy, Jest/Vitest,
Playwright, OpenAPI and Buf breaking-change reports, and Terraform plan JSON. A gate may use
`verification: mechanical` only when a registered parser successfully validates the artifact and
records its own name/version.

**Affected files.** `src/claude_kit/evidence.py`, `src/claude_kit/pipeline.py`, schemas, CLI, rules,
orchestrator, tests, and documentation.

**Acceptance criteria.** Unknown formats cannot be mechanical; malformed or contradictory reports
fail closed; parser output contains normalized result/counts; every advertised adapter has positive
and negative fixtures; agent-cited evidence remains accurately labeled agent-enforced.

**Migration concerns.** Existing ledger entries stay readable as `agent` or legacy; no historical
entry is upgraded to mechanical without re-parsing its retained artifact.

**Test plan.** Golden fixtures per format, truncated/hostile XML/JSON, parser-version migration,
format confusion, oversized artifacts, and property tests that no parser exception closes a gate.

## B. Introduce a versioned evidence envelope

**Rationale.** Evidence paths and hashes alone omit producer, command, commit, timing, exit code, and
parser identity, making stale or misattributed evidence difficult to reject.

**Proposed design.** Define a schema-versioned envelope containing run/gate identity, base/head SHA
and dirty state, producer/version, argv/cwd/exit code/timestamps, artifact path/format/hash, normalized
result, and parser name/version. Bind the envelope digest into the gate ledger.

**Affected files.** New evidence models/schema, `pipeline.py`, CLI, capture tooling, artifact
templates, docs, and tests.

**Acceptance criteria.** Required fields are schema-validated; path containment applies; command
arguments remain an array; envelope commit/run/gate must match the active run; changing envelope or
artifact invalidates the gate; secrets are redacted or the envelope is refused.

**Migration concerns.** Legacy path/hash entries remain readable with an explicit weaker-evidence
warning. Migration must never invent producer or command metadata.

**Test plan.** Schema negatives, stale SHA/run/gate cases, dirty-worktree handling, hash mismatch,
redaction fixtures, and round trips across supported schema versions.

## C. Add signed evidence and release provenance

**Rationale.** A local digest stored beside mutable evidence is content-integrity checking, not
tamper resistance against a writer able to change both files.

**Proposed design.** Evaluate in-toto Statements wrapped in DSSE, Sigstore keyless signing, SLSA
provenance, and GitHub artifact attestations. Select the smallest interoperable envelope and define
offline verification plus identity/issuer policy.

**Affected files.** Evidence schemas, release workflows, verification CLI, security/architecture
docs, and operations runbooks.

**Acceptance criteria.** Verification authenticates subject digest and signer identity; unsigned
evidence is labeled, not silently trusted; keyless identity/issuer constraints are explicit;
revocation/outage behavior is documented; release artifacts carry provenance.

**Migration concerns.** Signing is additive at first. Older unsigned evidence remains usable only at
its accurately labeled assurance level.

**Test plan.** Valid signature, wrong subject, wrong identity/issuer, modified envelope, expired
certificate, transparency-log outage, offline verification, and key-rotation fixtures.

## D. Replace security-critical shell hooks with a portable runtime

**Rationale.** Current Bash/`jq` guards no-op outside a compatible POSIX environment. This expands
issue #73.

**Proposed design.** Ship a small cross-platform executable entry point that reads JSON on stdin,
writes structured hook JSON on stdout, sends diagnostics to stderr, and exposes `self-test`. Port the
security-critical guards first; define explicit fail-open/fail-closed policy per hook.

**Affected files.** `src/claude_kit/hook_runtime.py`, hook registry/generated files, shell shims,
doctor, packaging, compatibility catalog, docs, and tests.

**Acceptance criteria.** Linux/macOS/Windows support; no `jq` dependency for ported guards; stdout is
always valid protocol JSON; security-hook parse/runtime failures follow documented policy; self-test
exercises every installed guard; legacy scripts remain only as a time-bounded compatibility shim.

**Migration concerns.** Preserve hook IDs and settings semantics; detect older Claude Code versions
before emitting unsupported hook output; document the shell-shim removal version.

**Test plan.** OS matrix, malformed/large stdin, Unicode and quoting, command-obfuscation corpus,
missing runtime, timeout, stdout contamination, and parity tests against the old guards.

## E. Reassess Python and operating-system support for 1.0

**Rationale.** Python 3.9 constrains safer filesystem/runtime APIs, while current CI does not prove
macOS or Windows behavior.

**Proposed design.** Measure usage and dependencies, then decide whether 1.0 raises the floor to at
least 3.11. Publish an OS/Python support matrix and test Ubuntu, macOS, and Windows across supported
versions.

**Affected files.** `pyproject.toml`, CI, compatibility docs, release notes, secure filesystem and
hook-runtime tests.

**Acceptance criteria.** A documented decision with evidence; every supported combination passes
install/upgrade/pipeline tests; wheel metadata matches docs; unsupported versions fail with an
actionable message.

**Migration concerns.** A floor increase is breaking and requires a deprecation release, release
notes, and a supported-version policy.

**Test plan.** Full matrix plus wheel install smoke, Windows junction/reparse tests, macOS filesystem
tests, and minimum-version syntax/import checks.

## F. Expand CI security coverage

**Rationale.** Supply-chain and workflow risks need independent automated checks beyond unit tests.

**Proposed design.** Add CodeQL, dependency review, pip-audit or OSV-Scanner, Gitleaks, actionlint,
zizmor, OpenSSF Scorecard, mutation testing, and a branch-coverage ratchet. Pin every action and
separate blocking PR checks from scheduled deep checks.

**Affected files.** `.github/workflows/`, Dependabot, security docs, repository-settings runbook.

**Acceptance criteria.** Critical/High reachable dependency findings block; secrets block; workflow
lint/security checks block; Scorecard is published without write-heavy permissions; mutation and
coverage thresholds cannot silently decrease.

**Migration concerns.** Baseline existing findings explicitly with owners and expiry dates; avoid a
permanent blanket allowlist.

**Test plan.** Seeded vulnerable dependency/secret/workflow fixture tests, actionlint/zizmor local
reproduction, permission audit, and scheduled-workflow dry runs.

## G. Add an installation lockfile

**Rationale.** `init-options.json` tracks installed files but not a complete, portable declaration of
payload, policy, compatibility, and component integrity.

**Proposed design.** Add `claude-kit.lock` with schema version, kit/payload digest, Claude Code
compatibility, selections, component/policy digests, MCP package integrity, and persisted-format
versions. Generate it from the staged install and verify it in strict validation/upgrade.

**Affected files.** Models, schemas, catalog/scaffold/upgrader/validator, CLI, docs, tests.

**Acceptance criteria.** Deterministic output; every selected component has a digest; payload/policy
drift is visible; strict mode rejects malformed/future locks; lock generation never follows unsafe
paths.

**Migration concerns.** Installs without a lock remain supported with a compatibility warning until a
documented upgrade creates one. User-edited configuration must not be falsely described as canonical.

**Test plan.** Determinism, payload drift, component removal, policy digest change, MCP integrity,
legacy install upgrade, future schema, and wheel/source parity.

## H. Harden the MCP catalog trust model

**Rationale.** Exact package versions improve reproducibility but do not express protocol,
capability, publisher, data-flow, authentication, maintenance, or transitive integrity.

**Proposed design.** Extend entries with protocol versions, capabilities, trust tier (`verified`,
`reference`, `experimental`, `deprecated`), source/publisher/license, authentication and OAuth
issuer/audience, write scopes, data classifications, egress allowlist, maintenance/review dates,
package/transitive integrity, health probe, and deprecation state.

**Affected files.** `catalog/mcp.yaml`, schema, lock generation, prompts/doctor/privacy report,
security docs, tests.

**Acceptance criteria.** Every live entry has complete provenance and review metadata; restrictive
defaults are machine-checkable; expired reviews warn/fail by policy; deprecated entries cannot be
newly selected without explicit acceptance; integrity is verified before execution.

**Migration concerns.** Add fields compatibly, assign honest initial tiers, and do not label an
unreviewed third-party server verified.

**Test plan.** Schema completeness, credential-ownership routing, scope escalation, egress union,
stale review/deprecation, integrity mismatch, and catalog migration fixtures.

## I. Build a privacy control plane

**Rationale.** Capture is opt-in but lacks preview, granular consent, retention, expiry, purge, and
machine-readable provenance controls.

**Proposed design.** Add capture preview and independent transcript/changed-file/commit-memory
opt-ins, allow/deny lists, retention/expiry, purge, `privacy-report --json`, provider disclosure, and
provenance for every captured memory.

**Affected files.** Capture catalog/hooks, prompts/models/scaffold/upgrader, privacy CLI, schemas,
SECURITY/docs, tests.

**Acceptance criteria.** Default remains off; consent is granular and persisted; preview exposes the
exact classes of data before enabling; expiry/purge are deterministic; provider and source provenance
are queryable; secret/PII filters fail safely.

**Migration concerns.** Existing single `capture_mode` selections map conservatively without enabling
new data classes; users are re-prompted before broader capture.

**Test plan.** Consent migration, preview accuracy, allow/deny precedence, retention clock, purge,
redaction failures, JSON report schema, and provider-disclosure snapshots.

## J. Evaluate policy-as-code

**Rationale.** Gate, risk, MCP data-flow, organization, profile, and release policies may outgrow
scattered Python/YAML/prose while still requiring one canonical enforcement source.

**Proposed design.** Prototype OPA/Rego for those six policy families behind a stable Python policy
interface. Compare determinism, portability, packaging cost, explainability, and offline behavior
against typed Python rules before adoption.

**Affected files.** New policy interface/prototype, catalogs, pipeline, validator, release preflight,
docs, tests.

**Acceptance criteria.** Decision record chooses adopt/reject with measurements; policy decisions
include explanations; unavailable policy runtime fails closed where required; no duplicated live
policy sources.

**Migration concerns.** Shadow-evaluate before enforcement; compare every old/new decision; version
policy bundles and preserve rollback.

**Test plan.** Golden decision matrix, differential old/new evaluation, malformed/unknown policy,
runtime absence, performance bounds, and bundle-version migration.

## K. Add metadata-only OpenTelemetry instrumentation

**Rationale.** Run/stage/gate/agent/tool reliability cannot be improved without structured timing and
failure signals, but prompts/responses must not be exported by default.

**Proposed design.** Instrument run, stage, gate, lane, agent, tool/MCP call, retries, hook latency,
token use, and failures. Default to local/no exporter and metadata-only attributes; make export an
explicit consented configuration.

**Affected files.** Pipeline and hook runtime, telemetry module, config/schema, doctor/privacy report,
docs, tests.

**Acceptance criteria.** No prompt/response/file content by default; stable semantic attributes;
trace/run correlation; exporter and endpoint are opt-in; telemetry failure never corrupts pipeline
state; privacy report enumerates emitted fields.

**Migration concerns.** No exporter on upgrade unless explicitly selected; schema/version attribute
changes follow a compatibility policy.

**Test plan.** In-memory exporter spans, redaction/content-absence assertions, retry/error paths,
disabled-mode zero export, exporter outage, and concurrency correlation.

## L. Define standards and protocol boundaries

**Rationale.** Interoperability suffers when MCP is used as a catch-all or when evidence/compliance
formats have no declared version boundary.

**Proposed design.** Publish a decision matrix for JSON Schema 2020-12, SARIF 2.1.0, JUnit,
coverage/LCOV, OpenAPI, AsyncAPI, Buf, CycloneDX/SPDX, SLSA/in-toto, MCP, A2A, ACP, LSP, OPA,
OpenTelemetry, and OSCAL. Use MCP for agent-to-tool, A2A for remote-agent interoperability, ACP for
editor-to-agent, LSP for language intelligence, OPA for policy, and OpenTelemetry for telemetry.

**Affected files.** Architecture/protocol docs, compatibility catalogs, schemas/parsers, future
integration code and tests.

**Acceptance criteria.** Each standard has purpose, supported versions, ownership, trust boundary,
and explicit non-goals; regulated-profile OSCAL use is evaluated without forcing it on other users.

**Migration concerns.** Existing custom formats receive adapters/deprecation timelines; protocol
selection does not silently change installed behavior.

**Test plan.** Conformance fixtures for adopted formats, unsupported-version failures, round trips,
and boundary tests proving no protocol is used outside its declared role.

## M. Adopt newer Claude Code capabilities deliberately

**Rationale.** New lifecycle and isolation features can improve safety, but enabling them without
compatibility and eval evidence would break older installations or expand trust.

**Proposed design.** Track the following as independently flaggable work packages:

1. Worktree isolation for write-capable agents (`isolation: worktree`).
2. Explicit `maxTurns` and effort limits.
3. Observed-trace-based tool allowlist reduction.
4. Read-only reviewer defaults.
5. `PostToolBatch` batching for formatting/checks.
6. `PostCompact` continuity restoration.
7. `ConfigChange` drift visibility.
8. `PermissionRequest` deterministic policy checks.
9. `TaskCreated`/`TaskCompleted` pipeline synchronization.
10. `WorktreeCreate`/`WorktreeRemove` lane lifecycle.
11. Stack-aware LSP integration.
12. Agent teams retained in an experimental profile until measured.
13. Opt-in monitors only after a hook-level trust review.

**Affected files.** Compatibility catalog, agents, hooks registry/generated files, profiles, pipeline,
doctor, eval harness, docs, tests.

**Acceptance criteria.** Each package declares a minimum Claude Code version and a fallback; feature
use is gated by compatibility data; reviewers cannot mutate by default; tool removal is supported by
trace evidence; experimental team/monitor features stay opt-in with measured reliability/risk.

**Migration concerns.** Existing older events and agents continue to work. Upgrades do not silently
enable worktrees, teams, monitors, or broader hook authority.

**Test plan.** Minimum/current Claude matrix, feature-floor tests, agent tool snapshots, mutation
attempts by reviewers, compaction/worktree/task event integration, and eval comparisons before/after.

## N. Establish project governance and maintainer continuity

**Rationale.** Release/security controls need named roles and succession mechanisms, but this project
must not invent maintainers or promise response capacity it does not have.

**Proposed design.** Draft `GOVERNANCE.md` and `MAINTAINERS.md` templates with repository-owner-filled
assignments. Define nomination/removal, release manager and backup, security response owner, target
acknowledgment times, protected-workflow ownership, succession, deprecation and supported-version
policy, and two-person review for release/security/workflow changes once multiple maintainers exist.

**Affected files.** New governance/maintainer docs, CODEOWNERS, SECURITY, CONTRIBUTING, repository
settings runbook.

**Acceptance criteria.** No fabricated names; authority and escalation are explicit; every critical
function has primary/backup placeholders; response times are targets rather than guarantees; the
two-person rule activates only when staffing permits; policies link to enforcement settings.

**Migration concerns.** The owner must ratify and fill assignments. Existing contribution rights are
not silently revoked by a draft.

**Test plan.** Documentation consistency/link checks, CODEOWNERS coverage checks, and a tabletop
exercise for maintainer loss and security-release handoff.

## O. Add repository security insights configuration

**Rationale.** Security-contact and policy metadata should be machine-readable where GitHub supports
it, while actual repository settings remain externally administered.

**Proposed design.** Evaluate and add `security-insights.yml` with contacts, policy locations,
supported versions, and disclosure metadata; document which fields are advisory versus GitHub-
enforced.

**Affected files.** `security-insights.yml`, SECURITY, governance docs, repository-settings runbook,
validation/tests.

**Acceptance criteria.** File validates against the selected specification; contacts are owner-
approved; no private address or invented role is published; documentation does not claim settings are
enabled merely because metadata exists.

**Migration concerns.** None until maintainers approve real assignments; use placeholders only in a
non-published draft if the format rejects empty contacts.

**Test plan.** Schema validation, link checks, and a manual GitHub Security-tab verification after
owner approval.
