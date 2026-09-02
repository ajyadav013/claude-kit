# Runtime support contract

Claude Code is the stable runtime today. Codex and `both` are **Preview**. The projection compiler,
artifact parsing, wheel/sdist installation, strict validation, shared-state interoperability, and
normalized hook adapters are covered by tests. Protected live-host smokes do not yet demonstrate
all Codex agent, permission, worktree, and hook behavior. A protected scheduled/manual workflow is
defined, but its presence is not a passing run, so it is not described as parity or promotion proof.

This document is normative for runtime projections. The architecture is recorded in
[ADR-001](adr/0001-runtime-projection-architecture.md).

## Status vocabulary

| Status | Meaning |
|---|---|
| **Native** | The host has a documented discovery surface and the projection preserves the intended behavior without a semantic downgrade. |
| **Adapted** | The compiler changes path, syntax, or invocation model, and tests demonstrate equivalent kit behavior. |
| **Degraded** | The component remains useful, but a host limitation or missing behavioral proof prevents an equivalence claim. |
| **Unsupported** | The host has no safe mapping, so the compiler omits the component and reports it. |

These labels describe mappings, not release maturity. A native host feature can still be Preview in
claude-kit until its renderer and behavioral tests pass.

## Current maturity

| Surface | Maturity | Release claim |
|---|---|---|
| Claude Code scaffold | Stable | Covered by the existing install, upgrade, strict-validation, and compatibility CI suites. |
| Claude Code plugin | Stable | Claude-native static plugin payload; narrower than the catalog-driven scaffold. |
| Codex scaffold | Preview | Native artifacts parse and install from source, wheel, and sdist; remaining live-host behavior gaps are listed below. |
| `both` scaffold | Preview | Emits both native discovery surfaces and one shared `.ckit`; promotion still requires protected cross-host behavior smokes. |
| Codex plugin | Preview | Isolated 0.147 and 0.149 marketplace add, native skill/hook discovery, plugin add/content/list/remove, and marketplace removal are exercised with credentials unset and `ON_USE` auth policy. Project projection is still scaffold-only. |
| Maker–checker coordinator | Preview | Configuration, exact-model argv routing, bounded iterations, typed evidence, passive role boundaries, patch validation, and injected-adapter resume/failure paths are deterministic-test surfaces. Protected credentialed native invocation and model-routing evidence remains a promotion gate, especially for Codex. |

## Normative scaffold matrix

| Capability | Claude projection | Codex projection | `both` projection | Notes |
|---|---|---|---|---|
| Project instructions | **Native**: `CLAUDE.md` | **Native**: managed `AGENTS.md` | **Native** | Preserve user text outside managed sections. Codex layers `AGENTS.md` by directory. |
| Engineering rules | **Native**: Claude rule files and path metadata | **Adapted**: bounded managed `AGENTS.md` layer plus complete `.ckit/rules/*.md` projections | **Adapted** | `.codex/rules` is an execution-policy surface, not a home for prose engineering rules. The renderer reports size-budget omissions explicitly. |
| Repository skills | **Native**: `.claude/skills` | **Adapted**: `.agents/skills` plus optional `agents/openai.yaml` | **Adapted** | Map manual-only behavior to `policy.allow_implicit_invocation: false`; do not copy Claude-only invocation variables unchanged. |
| Maker–checker skill and coordinator | **Degraded**: native `/maker-checker` discovery calls the bounded managed coordinator, but protected credentialed execution evidence and project test-command execution remain incomplete | **Degraded**: native explicit-only `$maker-checker` discovery uses the same coordinator and the exact-pinned passive Codex lane; protected credentialed routing and revision/resume behavior are not yet proven | **Degraded** | The project-scoped pair is stored once under `.ckit`; each role names one installed concrete provider and an inherited, tier, or exact model policy. Both built-in native paths are tool-denied and receive the same bounded, filtered, heuristically redacted projection of tracked UTF-8 text for semantic read/search. A `snapshot_kind: maker-checker` variant in the one shared pipeline snapshot freezes requested bindings and supports exact-ID resume without substituting later configuration. The coordinator uses a fresh passive reviewer, applies code only through a validated patch into a preserved worktree, and never treats PASS as merge/external-action authority. Current deterministic checks are artifact non-emptiness and, for code, `git diff --check`; project tests/lint/build are not run. |
| Slash commands | **Native** | **Adapted** as explicit skills | **Adapted** | Codex has no exact project slash-command analogue for the shipped Claude command files. |
| Custom agents | **Native**: Claude agent Markdown | **Degraded**: `.codex/agents/*.toml` is native syntax, but protected named-role behavior has not yet produced recorded green evidence | **Degraded** | Codex requires `name`, `description`, and `developer_instructions`; renderer maps model, effort, sandbox, MCP, and skill settings only when semantics are known. File generation and parsing alone are not a behavior proof. |
| Lifecycle hooks | **Native** | **Degraded**: native command handlers are projected, but protected host allow/block/advisory/Stop behavior has not yet produced recorded green evidence | **Degraded** | Event names overlap, but trust, matcher coverage, input/output fields, and blocking behavior must be tested per host. Only command handlers currently execute in Codex. |
| MCP configuration | **Native**: `.mcp.json` | **Adapted**: semantic merge into `.codex/config.toml` | **Adapted** | Codex uses native `env_vars`, `http_headers`, and `env_http_headers`; unsupported `${ENV}` argument/URL interpolation and environment renaming fail closed. `postgres`, `mongodb`, `azure_devops`, and `repowise` are therefore Claude-only until they have a safe native Codex launch contract. Each selected server retains declared runtime support, authentication mode, and health-check intent in the shared snapshot. A selected server is required: projection fails closed if any requested host is unsupported, while `doctor --mcp` reports the declaration without launching third-party servers. Preserve unknown user tables and keys. |
| Model tiers | **Adapted**: semantic fast/balanced/deep tiers map to Claude model aliases | **Degraded**: tier intent is preserved, but generated agent TOML and maker–checker tier bindings deliberately inherit the user's Codex model | **Degraded** | No provider model name appears in canonical sources. A maker–checker owner may configure an exact model ID, which is passed as a safe native argv element; `probe` validates only its shape and does not prove access. Codex does not receive a hard-coded model merely to imitate Claude aliases. |
| Per-agent permissions | **Degraded**: exact tools and `permissionMode` are projected, deployment credentials are withheld, and managed path deltas are verified; Claude has no portable OS-enforced shell-network boundary | **Adapted**: native per-role sandbox, feature/MCP clamps, command-network denial, secret-filtered shell environment, and managed path-delta verification | **Degraded** | Host controls are intentionally not described as interchangeable. Neither unattended adapter attests external mutation. |
| Orchestration and role routing | **Degraded**: Preview managed execution can run exact-tool no-shell roles; Claude stream-JSON carries bounded active corrections, while shell roles stop without descendant containment | **Degraded**: the bundled adapter admits only passive read-only, nondelegating roles on exact compatibility-pinned hosts after fail-closed feature and MCP probes; the optional app-server backend has deterministic, credential-free protocol evidence only | **Degraded** | `ckit pipeline run --provider …` freezes the workflow, gates, owners, conditions, retries, history, and attestations. Mode E requires an explicit frozen program manifest and adds typed waves, units, budgets, evidence, program gates, attempts, and checkpoints. The default isolated one-shot Codex `exec` path accepts queued messages before start. An explicitly selected app-server backend uses an ephemeral read-only thread for bounded `turn/steer` and `turn/interrupt`; it is not the default and has no credentialed inference evidence. The bundled adapters stop before Mode E shell/write units and every irreversible unit; those require independently proven physical containment or an external approval broker. |
| Worktree isolation | **Adapted**: managed execution defaults to one run-owned integration worktree | **Degraded**: the same exact-path fallback is adapter-tested, but protected live-host behavior is not yet proven | **Degraded** | Dirty application state fails closed. All managed stages share the run worktree so dependent review sees prior changes; the worktree is preserved and never auto-merged into the main checkout. |
| Gate enforcement | **Native to the kit** | **Native to the kit** | **Native to the kit** | The Python ledger is the enforcement authority; prose and hooks are guardrails. Managed PASS/accepted-risk additionally requires the frozen owning stage to have succeeded. Cross-runtime tests prove the same gate-definition digest. |
| Managed human approval | **Unsupported** | **Unsupported** | **Unsupported** | A generic local file and claimed resolver identity are not a trustworthy stage/attempt/workspace-scoped, one-shot authorization. Managed approval remains pending; rejection is only a replan/abort signal. Legacy/manual approval records remain compatible. |
| Continuity and pipeline state | **Native to the kit**: `.ckit` | **Native to the kit**: `.ckit` | **Native to the kit**: one shared `.ckit` ledger | Fresh installs never create a host-specific second state plane. |
| Catalog stack/profile/scope resolution | **Native** | **Native** | **Native** | Runtime stays outside `Selection`; `catalog.resolve()` receives no host value. |
| Ownership-aware upgrades | **Native** | **Native** | **Native** | Runtime renderers feed the same checksum, managed-section, semantic-merge, sidecar, and journal machinery. |
| Learning capture | **Adapted**: transcript/change-set capture into `.ckit/agent-memory` | **Degraded**: an isolated read-only classifier returns strict JSON to a trusted contained writer; historical transcript catch-up does not exist | **Degraded** | Capture is opt-in. Codex receives only a bounded sensitive-path-filtered/redacted diff, has local tools disabled, and never writes the workspace itself. |
| Ticket telemetry | **Adapted**: Claude transcript metadata can refresh the board | **Unsupported** for automatic host telemetry | **Degraded** | The board still renders from the shared ticket store; Codex emits an explicit no-op instead of reading a Claude transcript. |
| Headless lifecycle automation | **Unsupported** | **Unsupported** | **Unsupported** | The versioned loop validates an already-completed run but refuses every new iteration before host launch. Portable process groups cannot prove descendant containment, so no automated gate-transition token is minted. |

## Plugin limits

| Component | Claude plugin | Codex plugin | Limit |
|---|---|---|---|
| Skills | **Native** | **Native** | Plugin-root `skills/` is documented by both host ecosystems. Host-specific metadata may still need adaptation. The static maker–checker skill remains unusable until a project scaffold creates `.ckit` and its owner configures the pair. |
| Hooks | **Native** | **Degraded** until parity smokes pass | Codex loads plugin `hooks/hooks.json`, requires trust for non-managed hooks, and has host-specific output semantics. Its self-contained static `protect-secrets` compatibility guard covers native `Read`/`read_file` envelopes only; shell/unified-exec read enforcement requires the exact-wheel project scaffold and normalized `ckit hook-run` adapter. `PermissionRequest` and `PostCompact` are not projected. |
| MCP declarations | **Native** | **Native** | Static plugin MCP declarations are supported; project-specific catalog selection is not. |
| Project instructions and scoped rules | **Unsupported** | **Unsupported** | Plugin installation does not run the compiler or manage project instruction files. |
| Project custom agents | Claude host discovery only | **Unsupported** | Codex's documented plugin package does not install project `.codex/agents/*.toml`. Use the scaffold. |
| Stack/profile/scope selection, `.ckit`, migration, upgrades | **Unsupported** | **Unsupported** | These require the pip scaffolder. |

## Codex facts used by the projection

- Codex reads layered [`AGENTS.md`](https://developers.openai.com/codex/guides/agents-md/) files
  before work begins.
- Repository skills live under [`.agents/skills`](https://developers.openai.com/codex/skills/),
  and manual-only behavior is expressed by `policy.allow_implicit_invocation: false`.
- Project custom agents are TOML files under
  [`.codex/agents`](https://developers.openai.com/codex/subagents/) with three required fields.
- Project hooks live in [`.codex/hooks.json` or `.codex/config.toml`](https://developers.openai.com/codex/hooks/).
  Plugin hooks use the same schema but require explicit trust and currently execute command handlers.
- A plugin requires [`.codex-plugin/plugin.json`](https://developers.openai.com/plugins/build/plugins),
  and its documented static component surfaces are skills, hooks, MCP declarations, apps, and assets.
- In this repository `.agents/plugins/marketplace.json` selects the generated
  `providers/codex/claude-kit` package root. Its relative manifest is `.codex-plugin/plugin.json`;
  there is intentionally no unused `.codex-plugin/plugin.json` at the repository root.
- Project MCP servers are configured under
  [`[mcp_servers.<name>]` in `.codex/config.toml`](https://developers.openai.com/codex/mcp/).

## Promotion gates

Codex and `both` remain Preview until all of the following are release-blocking checks:

1. Canonical golden trees pass for `claude`, `codex`, and `both`, plus the full
   profile-by-stack-by-scope invariant matrix.
2. Every generated Codex skill is discoverable, every custom-agent TOML parses, and generated
   instructions load from the intended directory scope.
3. Native host smokes exercise skill arguments, manual-only routing, subagent personas,
   `SessionStart`, blocking `PreToolUse`, advisory/post-tool behavior, and `Stop`. Maker–checker
   smokes additionally exercise exact maker/reviewer model routing, fresh-reviewer isolation,
   feedback revisions, resume, and fail-closed paths on protected credentialed hosts.
4. Codex-only output contains no operational dependency on `.claude`, `CLAUDE.md`, the `claude`
   executable, or Claude-only invocation variables.
5. A `both` smoke proves that the two hosts read and update the same gate-history digest and
   `.ckit` state.
6. Clean wheel and sdist installs contain both host manifests and reproduce the source-checkout
   outputs.
7. Legacy `.claude` state migrates non-destructively and an interrupted migration resumes safely.

Until those gates pass, documentation and release notes must use “Preview” and identify degraded or
unsupported mappings explicitly.

## Protected behavior workflow (defined, not yet proven green)

`.github/workflows/protected-host-behavior.yml` is isolated from push and pull-request CI. It runs
only on a weekly schedule or manual dispatch, requires the `protected-host-behavior` GitHub
environment, refuses a non-default-branch ref, and exercises the audited minimum/current Claude
Code and Codex pairs. Each lane builds one wheel from the selected default-branch checkout,
installs that exact wheel, and scaffolds `--runtime both` before invoking either host.

The fixture uses the generated `using-agent-skills` skill and generated read-only
`risk-classifier` role, plus a randomized manual-only probe skill for argument propagation. It
checks instruction discovery, `SessionStart` exactly once, named subagent startup, blocking
`PreToolUse` through the exact-wheel generated `protect-secrets` policy (including Codex's native
shell/unified-exec `cat .env` path and its narrowly parsed explicit-reader contract), advisory
`PostToolUse`, the exact generated continuity `Stop` handler's native one-shot
`decision: block`/loop-guard contract, and a common Mode-D run gate-definition digest. The full installed catalog digest is
recorded separately because mode projection intentionally produces a different digest. Model
processes remain read-only. Verifier expectations for random discovery values and the blocked
canary use domain-separated SHA-256 commitments; neither the control file nor receipts contain a
plaintext answer oracle. A metadata-only proxy replays the exact scaffolded generated guard,
relays its native output unchanged, and binds the provider-specific exit/output hashes to that
handler's command digest. After validating Claude's commitments, the deterministic
coordinator binds the receipt to project-contained evidence, records zero findings, and closes the
real `code-review` gate. Codex must observe the resulting `build-green` stage and one-entry gate
history before its commitment-only receipt can close that gate and complete the same `.ckit`
pipeline.

The randomized discovery canaries are additionally protected by a harness-only read boundary:
instruction, skill, and agent definitions cannot be opened as tools, and Codex shell reads are
limited to exact `cat` operations over the fixture's STACK, pipeline snapshot/current evidence,
harmless control, and deliberate `.env` denial target. Broad searches and unparsed Python, Git,
find, command-substitution, or recursive reads are denied and make verification fail.

Credentials are deliberately host-owned: Claude reads an out-of-workspace `apiKeyHelper`. The
OpenAI key has exactly two protected channels: the exact-wheel coordinator passes it only to the
pinned passive `CodexProcessDispatcher` host process used for the managed `classify` proof, and the
separate native-behavior probe runs through the pinned official `openai/codex-action` key proxy
under the built-in read-only permission profile. Neither channel exposes it to project tools or
persists it in the fixture, and the isolated Codex home trusts only the canonical prepared project
path.
That same coordinator channel also runs a separate, explicitly fixture-seeded standard-profile
Mode A project: coordinator-owned typed predecessor stages close `spec-complete` through public
ledger APIs without a native-host claim, then the exact-wheel Codex adapter runs only the canonical
passive `planning-merge`/`em-reviewer` owner. Its typed `architecture-plan` and PASS
`review-verdict` must produce the root-owned owner-attempt bundle that closes `em-approved`; the
harness verifies the exact gate-history digest and stops before the next broader stage.
The pinned action rejects hook-trust bypasses under protected profiles. Before it drops sudo, the
workflow therefore copies the exact prepared `.codex/hooks.json` byte-for-byte into Codex's
root-owned `/etc/codex/hooks.json` system layer, which Codex treats as managed policy. It fails
closed if `/etc/codex` already exists and verifies source/destination hashes, ownership, and modes;
ordinary CI and user workflows install no system hook policy. The verifier still binds every
generated handler decision to its prepared command digest rather than trusting model prose.
Probe hooks start through `env -i`; the retained generated hooks run only after the host invocation
has been given no provider secret in its child environment. The ordinary `ci.yml` workflow receives
neither credential. Repository setup for the protected environment is documented in
[`operations/github-repository-settings.md`](operations/github-repository-settings.md).

This workflow has not yet produced a successful protected run in this repository, so it is a test
definition, not evidence. Even after it is green, it proves a bounded native discovery/role/hook
slice, ordered Mode-D ledger continuity in both provider directions, and one fixture-seeded
canonical Mode-A `em-reviewer` gate-owner transition. The fixture-seeded predecessor stages are
explicitly excluded from the native-host claim. It does not make the bundled Codex
managed process backend generally safe: the orchestration row remains Degraded because only the
passive lockdown lane runs without descendant containment. Shell, write, delegation, browser, MCP,
and external-effect roles remain Unsupported with the bundled backend until descendant-process
containment has an independently proven implementation.

The optional Codex app-server path compensates for the pinned host's lack of
`--ignore-user-config` by creating a fresh mode-0700 `CODEX_HOME` and home/XDG directories. It
copies no developer configuration; when present, only a canonical, owner-only, regular
`auth.json` is copied mode 0600 into the temporary home and deleted at terminal cleanup. A
keyring-only login is therefore unavailable to this path, while `CODEX_ACCESS_TOKEN` and
`OPENAI_API_KEY` remain explicit supported credential inputs. Codex app-server also lacks
`--ignore-rules`: this is safe
only for the admitted passive lane because every command, hook, plugin, MCP, app, browser, search,
delegation, and write surface is denied and project instructions are suppressed. It is not a basis
for enabling broader roles or claiming host parity.

The app-server backend must be selected explicitly; ordinary construction continues to use
one-shot `codex exec`:

```python
from claude_kit.process_dispatch import CodexAppServerBackend, CodexProcessDispatcher

dispatcher = CodexProcessDispatcher(
    project_root,
    backend=CodexAppServerBackend(),
)
```

## Evidence already covered

The Preview label is not a claim that the renderer is untested. The current suite covers:

- deterministic `claude`, `codex`, and `both` artifact trees from a source checkout, wheel, and
  sdist, followed by strict validation and `doctor`;
- isolated provider plugin lifecycles, including the official Claude 2.1.239 strict validator and
  non-credentialed Codex 0.147/0.149 marketplace/plugin add-content-list-remove plus app-server
  discovery sequences;
- JSON, YAML, and TOML parsing, skill/agent counts, forbidden-provider-leakage checks, and the Codex
  `AGENTS.md` size budget;
- every runtime transition, explicit native-surface removal confirmation, backup/rollback behavior,
  and one shared `.ckit` manifest and ledger;
- managed Mode A–D graph progression with injected contained backends, frozen workflow/gate-owner/
  condition contracts, exact typed stage/gate evidence, normalized finding indexes, root-owned
  owner-attempt bundles, bounded process output artifacts, cancellation, retry, required-isolation
  refusal, built-in-adapter refusal of uncontained Claude shell routes, and Codex's exact-pinned
  passive read-only lockdown lane plus refusal of every shell, write, delegation, browser, MCP, or
  external-effect route;
- maker–checker policy validation and migration, same-provider and cross-provider dispatch routing,
  strict maker/reviewer envelopes, first-pass and revised PASS, unchanged/stale/exhausted failure,
  constrained code-patch application, cancellation, and injected-adapter resume without model
  substitution;
- Mode E manifest/run binding, audit and verification ordering, unit/gate no-replay, budgets,
  content-addressed typed evidence, Git-index-aware workspace checkpoints, cross-provider resume,
  and fail-closed physical-containment/irreversible-operation boundaries;
- cross-runtime gate updates in both directions with an unchanged gate-definition digest; and
- normalized positive allow/block controls for the supported hook adapter events.

Those deterministic tests do not substitute for a recorded green run of the protected workflow, or
for the remaining managed-execution promotion gaps named above.
