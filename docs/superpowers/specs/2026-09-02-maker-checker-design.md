# Configurable Maker–Checker — Design

**Date:** 2026-09-02 · **Status:** approved by user (Codex first-class) · **Target:** staged delivery

## Context

claude-kit can install native Claude Code, Codex, or dual-runtime projections, and its SDLC
workflow already distinguishes implementation routes from review routes. It does not yet let a
project owner persist one model as the maker and another as the independent reviewer, route the
two roles to different providers in one managed run, or execute a bounded reviewer-feedback loop.

The desired experience has three parts:

1. During a runtime-aware `ckit init`, optionally ask which provider/model should make the work and
   which should review it.
2. Let the project owner inspect, change, or disable that pair later.
3. Provide one explicit `maker-checker` skill, invocable natively from either Claude Code or Codex,
   that completes a coding, design, or specification deliverable through the configured pair and
   returns the reviewed artifact.

This follows the evaluator–optimizer pattern described by
[Anthropic](https://www.anthropic.com/engineering/building-effective-agents), while keeping the
provider boundary explicit as recommended by the
[OpenAI Agents SDK orchestration guidance](https://openai.github.io/openai-agents-python/multi_agent/).
The official [Codex plugin for Claude Code](https://github.com/openai/codex-plugin-cc) is useful
evidence that cross-provider delegation is viable, but claude-kit needs provider-neutral,
ledger-backed behavior rather than a provider-specific prompt bridge.

## Goals

- Persist project-scoped maker and reviewer bindings in the single shared `.ckit` control plane.
- Support Claude and Codex as either role, including two different models on the same provider.
- Let Codex be the invoking/coordinating host, not merely a reviewer called from Claude.
- Install a Codex-native `$maker-checker` skill for `codex` and `both` projections without requiring
  an active Claude session.
- Ask during interactive installation without adding surprise model calls under `--defaults`, EOF,
  or non-interactive operation.
- Allow later configuration through a transactional CLI.
- Expose an explicit provider-neutral skill for code, design, and specification work.
- Give the reviewer a fresh, read-only context containing the frozen contract, artifact, and
  verification evidence—not the maker's narrative or hidden reasoning.
- Treat reviewer findings as semantic feedback, retain every iteration, and stop after a bounded
  number of revisions.
- Preserve legacy single-provider workflows when no maker–checker policy is configured.

## Non-goals for the first release

- Storing API keys, login tokens, endpoints, or other credentials.
- Treating a consumer ChatGPT conversation as an execution host. The OpenAI execution host in the
  initial release is Codex; further hosted-model adapters can implement the same contract later.
- Adding runtime or model choices to `Selection` or branching inside `catalog.resolve()`.
- Writing provider names or exact model identifiers into canonical agent or skill definitions.
- Letting a reviewer edit the artifact, delegate work, approve its own changes, or authorize merge,
  deployment, publication, purchase, or another external effect.
- Changing an already-started run when project defaults are reconfigured.
- Replacing `doubt-driven-development`. That skill remains an optional adversarial check on an
  in-flight decision; `maker-checker` is the explicit end-to-end production loop.

## Terminology

- **Maker** — the execution slot that creates or revises the deliverable.
- **Reviewer** — the independent, read-only execution slot that evaluates the current deliverable.
  The user-facing skill calls this role the checker; the persisted field is `reviewer` because it
  describes the role precisely.
- **Persona/route** — the domain role, such as developer, UI designer, spec writer, or code reviewer.
- **Binding** — one concrete provider plus one model selection for an execution slot.
- **Iteration** — one maker artifact followed by one review of exactly that artifact digest.
- **Revision** — a new maker attempt prompted by a well-formed reviewer `FAIL`.

Persona, execution slot, and runtime binding remain orthogonal:

```text
developer / designer / spec writer  -> maker    -> configured provider + model
code / design / spec reviewer       -> reviewer -> configured provider + model
```

## Product contract

### Persisted configuration

The normalized project policy is an optional top-level `execution` field in
`.ckit/config/init-options.json`. The same shape is accepted under `execution` in an init YAML
file:

```yaml
runtime: both

execution:
  strategy: maker-reviewer
  maker:
    provider: claude
    model:
      kind: tier
      value: deep
  reviewer:
    provider: codex
    model:
      kind: exact
      value: <provider-model-id>
  max_revisions: 2
```

The typed contract is equivalent to:

```python
ModelChoice(kind="inherit" | "tier" | "exact", value=str | None)
WorkerBinding(provider="claude" | "codex", model=ModelChoice(...))
ExecutionPolicy(
    strategy="maker-reviewer",
    maker=WorkerBinding(...),
    reviewer=WorkerBinding(...),
    max_revisions=2,
)
```

An absent `execution` field means legacy single-provider behavior. It does not silently enable a
second model call.

Validation rules:

- A worker provider is concrete; `both` is never a worker provider.
- Every referenced provider is present in the installed runtime set.
- `tier` accepts the semantic `fast`, `balanced`, or `deep` values and requires `value`.
- `exact` accepts one bounded, syntax-safe native model identifier and requires `value`.
- `inherit` forbids `value` and uses the host's configured default.
- `max_revisions` is an integer from 0 through 3; the default is 2. This permits at most three
  complete maker/reviewer iterations: the initial attempt plus two revisions.
- The same provider and model may fill both slots, but `show`, `doctor`, and run preflight warn that
  review independence is reduced.
- Prompts, tools, permissions, credentials, and API keys are not configurable through this object.

Exact model availability changes faster than the package. Configuration validates shape and host
compatibility; a live preflight validates login, executable, selected model, and required runtime
capabilities before a task sends project content.

### Installation UX

Runtime selection remains outside provider-neutral catalog selection and happens first. After the
runtime is known, an interactive runtime-aware install asks:

```text
Maker–checker execution
  Configure an independent maker + reviewer pair? [y/N]

Maker provider: Claude | Codex
Maker model: provider default | fast | balanced | deep | exact model id

Reviewer provider: Claude | Codex
Reviewer model: provider default | fast | balanced | deep | exact model id

Maximum revisions [2]

Summary
  Maker:    Claude / deep
  Reviewer: Codex / <provider-model-id>
  Revisions: 2
```

Only providers in the selected runtime are offered. A Claude-only install can still use two Claude
models; a cross-provider pair requires `runtime: both`. The installer never broadens the runtime
implicitly.

`--defaults`, EOF, and non-interactive installs leave the feature disabled. A config-file mismatch
fails before any filesystem mutation and explains how to request the missing runtime. Installation
does not perform a paid task inference.

### Codex is a first-class host

Codex support is part of the feature's acceptance contract, not a later compatibility importer. A
`codex` or `both` installation must:

- project the canonical skill to `.agents/skills/maker-checker/SKILL.md` using Codex-native
  frontmatter and references;
- project `agents/openai.yaml` with `policy.allow_implicit_invocation: false`, so the explicit-only
  consent boundary is preserved;
- expose the user invocation as `$maker-checker <task>` rather than copying Claude slash syntax;
- run `ckit maker-checker configure|show|disable|probe|run` against the same shared `.ckit` state;
- allow a Codex-only project to bind different Codex models as maker and reviewer;
- allow a dual-runtime project opened in Codex to route either slot to Claude or Codex; and
- coordinate, resume, and report a run without an active Claude Code conversation or Claude-owned
  state file.

The equivalent Claude projection remains `/maker-checker <task>`. Both host entrypoints call the
same provider-neutral Python coordinator and ledger contract; neither host owns a second copy of
configuration or evidence.

Codex remains Preview while its protected credentialed invocation gates are open. Generated skill
discovery alone is insufficient: the feature is not reported as behaviorally available on Codex
until native invocation, model routing, reviewer isolation, feedback cycles, resume, and failure
paths have recorded green Codex-host evidence. Until then, `doctor` and the fidelity matrix report
the exact Degraded or Unsupported capability rather than silently handing work to Claude.

### Configure-anytime CLI

Add a dedicated command group:

```text
ckit maker-checker show [PROJECT]
ckit maker-checker configure [PROJECT]
ckit maker-checker configure [PROJECT] \
  --maker-provider claude --maker-model-tier deep \
  --reviewer-provider codex --reviewer-model-id <provider-model-id> \
  --max-revisions 2
ckit maker-checker disable [PROJECT]
ckit maker-checker probe [PROJECT]
```

Interactive `configure` pre-fills the current values. Non-interactive configuration requires a
complete pair, so an omitted flag cannot accidentally retain or invent half of a binding. The
operation uses the existing project containment, mutation lease, journal, and transactional-write
machinery and preserves unknown structured keys.

If a requested provider is not installed, configuration fails with an exact remedy such as
`ckit upgrade PROJECT --runtime both`; it does not perform that transition. A runtime transition
that would remove a provider referenced by the policy is refused until the policy is changed or
disabled.

Reconfiguration changes defaults for the next run. A started run retains its frozen binding and
reports that fact. If the active-run lease makes a safe config transaction impossible, the command
fails cleanly rather than editing around the lease.

No command stores or prints credentials. `probe` reports provider/model availability and capability
status, with sensitive host output redacted and bounded.

## `maker-checker` skill contract

The new canonical core skill is an explicit entrypoint, projected through the normal Claude and
Codex renderers. It is not the enforcement engine. Its description is:

> Complete a code, design, or specification deliverable through the configured maker and
> independent reviewer models, using artifact-bound evidence and bounded revision cycles. Use when
> the user explicitly requests maker-checker, dual-model, or cross-model execution; not for ordinary
> single-model work or unapproved external actions.

Expected invocation accepts a task plus an optional `kind=auto|code|design|specification`:

```text
Claude Code: /maker-checker <task>
Codex:       $maker-checker <task>
CLI:         ckit maker-checker run --kind auto --task '<task>'
```

In `auto`, the coordinator infers the deliverable type and asks one question only when the
distinction changes the artifact or review contract. Design is further classified as UI/product
design or technical/system design.

The skill runs only from the coordinating session. It must not be attached to a worker persona or
recursively invoked by the maker or reviewer. Static plugin installation alone cannot configure it;
the skill fails clearly when the project has no `.ckit` state or maker–reviewer policy.

An invocation authorizes one bounded maker–reviewer run over the declared project scope. Persisted
preferences are not perpetual authorization to send arbitrary content to an external model.

### End-to-end behavior

```text
explicit skill invocation
        |
load policy + live preflight
        |
freeze task contract + pair binding + digests
        |
spawn fresh maker ----> artifact ----> deterministic checks
        ^                                  |
        |                                  v
structured findings <---- fresh read-only reviewer
        |
        +-- PASS + green evidence -------> final artifact
        |
        +-- FAIL, budget remains --------> new maker revision
        |
        +-- conflict / exhausted budget -> human stop
```

1. **Load and announce**
   - Read the persisted policy.
   - Resolve semantic tiers at dispatch time.
   - Show the maker/reviewer provider and requested model before inference.
   - Fail closed on missing auth, model, containment, or required capabilities.

2. **Freeze the contract**
   - Record objective, deliverable kind, acceptance criteria, non-goals, allowed read/write scope,
     artifact location, and deterministic verification commands.
   - Resolve material ambiguity through the existing human-stop mechanism.
   - Freeze the contract digest and slot-to-provider/model binding before the first dispatch.

3. **Make**
   - Route the appropriate domain persona through the maker slot.
   - Produce the deliverable in an owned workspace or through a constrained patch/artifact channel.
   - Run the declared deterministic checks and bind their evidence to the artifact digest.
   - Do not ask the maker to approve its own work or expose hidden reasoning as evidence.

4. **Check independently**
   - Start a new read-only, nondelegating reviewer session for every iteration.
   - Supply only the frozen contract, current artifact or diff, and deterministic evidence—not the
     maker's scratch reasoning, confidence statement, or prior reviewer prose.
   - Require a typed `PASS` or `FAIL`, criterion-by-criterion coverage, stable finding IDs, severity,
     citations, and residual risks.
   - The trusted coordinator validates and persists the response; the reviewer never writes state.

5. **Revise within budget**
   - A valid `FAIL` is a semantic result, not a transport failure and not a call to `retry()`.
   - Spawn a new maker attempt with the structured findings. Each finding becomes `fixed`, `disputed`
     with evidence, or `human-required`.
   - Review only a new artifact digest. An unchanged artifact cannot consume another review cycle.
   - Stop for a person on exhausted revisions, unresolved disagreement, conflicting evidence,
     material scope growth, or a protected/external action.

6. **Finish**
   - Return the maker's current artifact—not reviewer prose—as the deliverable.
   - Report exact requested bindings, actual models when the host can attest them, iteration count,
     checks, resolved findings, and remaining low/informational risks.
   - Reviewer PASS never authorizes merge, publication, deployment, purchase, deletion, or another
     external effect.

### Deliverable-specific routing

| Kind | Maker route | Reviewer lens | Required deterministic evidence |
|---|---|---|---|
| Code | developer appropriate to selected stack | correctness, security, maintainability, spec compliance | scoped diff plus declared tests/lint/build/type checks |
| UI/product design | UI/product designer | user goal, states, accessibility, consistency, feasibility | artifact/render existence plus available design checks |
| Technical/system design | technical architect/spec writer | requirements, boundaries, failure modes, operability | schema/link/diagram validation where available |
| Specification | spec writer | completeness, testability, contradictions, scope, acceptance criteria | document/schema/link validation where available |

The skill uses progressively disclosed, provider-neutral rubric references for code, UI/product
design, technical/system design, specification, and the common verdict schema. It does not add all
specialist personas to the lean profile. The installed execution feature either projects a small,
truthful pair-role bundle or uses generic artifact roles with the selected stack context.

## Authoritative coordinator

Prompt prose alone cannot guarantee isolation, routing, bounded cycles, or trustworthy PASS. Add a
Python coordinator, tentatively `src/claude_kit/maker_checker.py`, and expose it through the skill and
`ckit maker-checker run`.

The coordinator is launched identically from Claude and Codex projections. Its authority comes from
the frozen `.ckit` contract, not the host that invoked it. Starting it from Codex must not select
Codex for both slots implicitly; the persisted maker and reviewer bindings remain authoritative.

The current six-operation dispatch protocol remains the base:

```text
spawn -> message -> wait -> collect -> retry -> cancel
```

Extend requests and attempts with an execution slot (`maker` or `reviewer`), requested model, and
binding digest. A routed dispatcher maps each slot to its provider adapter and remembers ownership
for later operations. It must support opposite providers and the same provider with different model
overrides.

Exact model overrides are injected as one native argv element at dispatch time. Generated agent
files continue to carry semantic model tiers only. Provider output is untrusted, bounded, and parsed
through the existing adapter boundary.

Transport failures may use the existing retry operation. Reviewer `FAIL` creates a new semantic
iteration and preserves the prior artifact and verdict. The workflow catalog's existing feedback
budgets do not currently drive such a loop; this design adds explicit feedback-cycle state rather
than overloading transient retry state.

## Frozen run and evidence contract

Before the first model dispatch, persist a versioned binding inside the existing pipeline snapshot:

```yaml
maker_checker:
  schema_version: 1
  policy_digest: <sha256>
  contract_digest: <sha256>
  bindings:
    maker:
      provider: claude
      requested_model: deep
    reviewer:
      provider: codex
      requested_model: <provider-model-id>
  max_revisions: 2
  iteration: 1
```

Each attempt records its execution slot, provider, requested model, actual model when attested by the
host, adapter version, contract digest, artifact digest, and predecessor attempt. Changing project
defaults does not change this record. Resume validates the frozen binding; drift or an unavailable
frozen endpoint produces a human stop rather than silently substituting another model.

Legacy runs without this subdocument retain their current provider-resume behavior.

Pair-specific typed evidence supplements, rather than weakens, the generic review-verdict contract.
A PASS is legal only when:

- the contract digest and reviewed artifact digest match the frozen current values;
- every acceptance criterion has a disposition and evidence;
- every blocking finding is resolved;
- declared deterministic checks are green;
- the frozen reviewer binding was used; and
- the reviewer read-only/nondelegating boundary is attested.

A disagreement remains visible in the ledger even when a later artifact passes. `BLOCKED` is a
human-stop state, not a reviewer verdict that can be mistaken for PASS.

## Safety and privacy

- Only the maker may request artifact mutation, limited to the frozen write boundary.
- The reviewer is always fresh-context, read-only, and nondelegating.
- Maker and reviewer never talk directly; the coordinator mediates typed, recorded handoffs.
- Repository instructions, untrusted artifacts, and model output cannot expand capabilities.
- Configuration contains no credentials or provider prompts.
- Invocation shows the selected endpoints before sending task content.
- Secret-bearing paths and values follow existing exclusion/redaction rules.
- External effects and irreversible actions retain their existing human approvals.
- Unsupported required host capabilities fail closed and remain visible in `doctor`.

## Schema, lifecycle, and compatibility

- Add `ExecutionPolicy` to `InstallRequest`, never `Selection` or `ResolvedPlan`.
- Add the policy to `InitOptions` and bump its schema from 2 to 3.
- Migrate schema 1 and 2 documents with `execution=None`; do not alter frozen 0.83 fixtures.
- Preserve the policy through preview, install, same-runtime upgrade, runtime transition, rollback,
  and manifest reconstruction.
- Include its digest in managed-run integrity validation.
- Preserve unknown structured keys during reconfiguration and upgrade.
- Keep one `.ckit` manifest, journal, snapshot, and evidence ledger for both providers.
- Treat Codex and `both` as Preview until their documented promotion gates are satisfied.
- Do not claim native parity merely because both provider files render.

## Canonical and generated surfaces

Source changes are expected in:

- `canonical/skills/core/maker-checker.md` and its provider-neutral rubric references;
- a provider-neutral maker–checker workflow/catalog definition and strict schema;
- model, prompt, CLI, runtime scaffold, upgrade, validation, dispatch, process-adapter, workflow
  executor, evidence, and pipeline modules;
- profile/feature projection metadata; and
- architecture, runtime-support, CLI, skill, and compatibility documentation.

The canonical skill may use semantic references such as `state://maker-checker-config` and
`workflow://maker-checker`. Renderers resolve those references. Canonical files never name Claude,
Codex, exact native models, host commands, or physical provider paths.

Generated Claude and Codex skill payloads are regenerated from canonical sources; they are never
hand-edited. Provider manifests are regenerated only when their catalog-owned metadata changes.

Expected generated discovery surfaces include:

```text
Claude project: .claude/skills/maker-checker/SKILL.md
Codex project:  .agents/skills/maker-checker/SKILL.md
                .agents/skills/maker-checker/agents/openai.yaml
Codex plugin:   providers/codex/claude-kit/skills/maker-checker/SKILL.md
                providers/codex/claude-kit/skills/maker-checker/agents/openai.yaml
```

The Codex plugin and project projection are generated from the same canonical skill but remain
distinct installation paths: a static plugin exposes the discoverable skill, while a runtime-aware
project install creates the `.ckit` configuration required to run it.

## Delivery plan

The destination contract includes code, design, and specification work. Delivery is staged because
the current managed executor selects one provider per invocation and the Codex adapter deliberately
admits only passive read-only roles without stronger descendant containment.

1. **Configuration foundation**
   - Typed schema and v1/v2 migration.
   - Interactive install/config parsing.
   - Transactional `show`, `configure`, `disable`, `probe` commands.
   - Upgrade/transition preservation and `doctor` output.

2. **Read-only artifact loop**
   - Authoritative coordinator, frozen binding, routed read-only dispatch, typed evidence, and
     bounded semantic revision state.
   - Specification and design artifacts use bounded structured model output; a trusted coordinator
     writes only the predeclared artifact path.
   - Exercise the loop when invoked from both Claude and Codex, including Codex-only and dual-runtime
     configurations.

3. **Safe coding loop**
   - Add dispatch-time exact model selection for both adapters.
   - Either attest independent write/shell containment or have the maker emit a constrained patch
     that a trusted coordinator validates and applies before running checks.
   - Enable code only when the required boundary is proven; otherwise report it as Unsupported,
     never silently fall back to an unconstrained process.

4. **Managed-workflow integration and promotion**
   - Connect pair slots to existing SDLC routes and feedback budgets.
   - Validate resume, cancellation, concurrency, drift, and protected credentialed hosts.
   - Update the normative fidelity matrix and promotion status from evidence.

## Verification plan

Focused tests cover:

- strict config parsing, interactive prompts, EOF/`--defaults`, and no-secret persistence;
- schema 1/2 to 3 migration and future-schema refusal;
- dry-run output, config/flag precedence, transactional reconfiguration, and provider-removal refusal;
- same-provider and cross-provider routing with exact/tier/inherited models;
- `$maker-checker` discovery and explicit-only policy in both the Codex project projection and
  generated Codex plugin;
- Codex as the invoking coordinator for Codex-maker/Codex-reviewer, Codex-maker/Claude-reviewer, and
  Claude-maker/Codex-reviewer bindings;
- proof that Codex invocation does not require a running Claude session or provider-local state;
- safe argv construction and unavailable model/auth/capability preflight;
- fresh read-only reviewer enforcement and binding attestation;
- first-pass PASS, FAIL/revision/PASS, unchanged digest rejection, disputed findings, exhausted
  revisions, timeout, cancellation, and resume;
- stale contract/artifact digests, incomplete criterion coverage, illegal PASS, and retained dissent;
- legacy unconfigured workflow behavior; and
- canonical skill projection, reference closure, profile reachability, and generated-payload drift.

After focused tests, run the repository's required pytest, ruff, mypy, shellcheck, generator drift,
documentation consistency, cross-reference, skill-description, runtime smoke, and build checks.

## Proposed decisions awaiting approval

1. Initial providers and invoking hosts are Claude Code and Codex; each may coordinate either
   provider as maker or reviewer, and the contract remains adapter-ready for more hosted model
   providers later.
2. Configuration is project-scoped in the shared `.ckit` manifest, not a machine-global preference.
3. The feature is opt-in at install and each job starts only through explicit skill/CLI invocation.
4. Models may be selected by provider default, semantic tier, or exact native identifier.
5. Two revisions are allowed by default and three is the hard maximum before a human stop.
6. Reconfiguration affects future runs; active runs keep a frozen provider/model binding.
7. Specification and design support lands before coding if the current write/shell containment gate
   is not yet provably satisfied.
