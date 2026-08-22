# claude-kit JSON Schemas

Draft 2020-12 JSON Schemas for claude-kit's **authored** data and **persisted** artifacts. They are
a *structural* quality layer on top of the *referential* checks in `claude_kit.validator` — they
catch shape/type typos (a missing `version`, a section that isn't a map, an org-pack component
missing its `existing` flag) that referential checks don't.

| Schema | Validates | Wired into |
|--------|-----------|------------|
| `catalog-stacks.schema.json` | `catalog/stacks.yaml` | `check_catalog` / CI |
| `catalog-profiles.schema.json` | `catalog/profiles.yaml` | `check_catalog` / CI |
| `catalog-mcp.schema.json` | `catalog/mcp.yaml` | `check_catalog` / CI |
| `catalog-capture.schema.json` | `catalog/capture.yaml` | `check_catalog` / CI |
| `catalog-org.schema.json` | `catalog/org.yaml` | `check_catalog` / CI |
| `claude-compatibility.schema.json` | pinned minimum/current Claude Code versions plus event, agent, skill, plugin, and MCP contracts | `check_catalog` / CI / `doctor` |
| `codex-compatibility.schema.json` | pinned Codex CLI versions, exact official validator-bundle hashes, and native feature/event/agent/skill/plugin capabilities | `check_catalog` / CI |
| `plugin-metadata.schema.json` | canonical Claude Code + Codex plugin identity and provider presentation metadata | `check_catalog` / CI / manifest generation |
| `canonical-agent.schema.json` | provider-neutral agent ID, description, capabilities, semantic model tier, permission/write/isolation/delegation policy, skills, and symbolic references | strict canonical loader / payload drift CI |
| `canonical-skill.schema.json` | provider-neutral skill metadata, invocation policy, capabilities, and body source | strict canonical loader / payload drift CI |
| `canonical-command.schema.json` | provider-neutral command aliases and request semantics | strict canonical loader / payload drift CI |
| `canonical-rule.schema.json` | provider-neutral rule body plus applicability and path-glob metadata | strict canonical loader / payload drift CI |
| `canonical-template.schema.json` | provider-neutral text template, format, destination role, and symbolic placeholders | strict canonical loader / payload drift CI |
| `workflow.schema.json` | stages, role routing, dependencies, parallel lanes, ordered/conditional gates, retries, evidence, findings policy, and operating modes | strict workflow loader / digest tests / CI |
| `org-pack.schema.json` | `templates/org/packs/<id>/pack.yaml` | `check_catalog` / CI |
| `mcp-lock.schema.json` | `.mcp.lock.json` (a project's resolved MCP lock) | `validate --strict` |
| `pipeline-snapshot.schema.json` | fresh `.ckit/state/pipeline-snapshot.json` (legacy `.claude/state/` remains readable during migration) | `validate --strict` |
| `program-manifest.schema.json` | a frozen, content-addressed Mode E program plan before any program worker is dispatched | strict loader plus manifest/run binding; the Preview program executor records waves, units, attempts, evidence, gates, budgets, and checkpoints in `pipeline-snapshot.schema.json` |
| `managed-approval.schema.json` | a detached, origin-bound authorization request/envelope and typed external-action receipt | strict managed-approval loader; schema validity alone is never authorization |
| `stack-catalog-snapshot.schema.json` | fresh `.ckit/config/stack-catalog.snapshot.yaml` (legacy `.claude/config/` remains readable during migration) | `validate --strict` |

## Required dependency and fail-closed behavior

Validation uses [`jsonschema`](https://pypi.org/project/jsonschema/) as a runtime dependency:

```
pip install claude-code-kit
```

The historical `schema` extra remains as a compatibility alias. If a damaged installation lacks
`jsonschema`, `validate --strict` fails closed rather than reporting an unvalidated artifact as safe;
non-strict catalog inspection emits a warning.

Canonical loaders additionally reject provider leakage rather than treating a schema-valid provider
literal as portable. Claude/Codex tool names, provider model names, permission syntax, physical host
paths, and host-only invocation variables belong in renderers. Symbolic references are resolved only
at projection time.

## Persisted runtime metadata

`.ckit/config/init-options.json` is governed by the typed `InitOptions` contract rather than a
standalone JSON Schema in this directory. Current schema v2 records:

- the provider-neutral `Selection`;
- one or more installed runtimes (`claude`, `codex`);
- `StateLayout.neutral()` paths;
- renderer and compatibility-catalog versions; and
- per-file path, SHA-256, owner, provider, and logical component ID.

A legacy schema-v1 document with no runtime is read as Claude-only. Explicit state migration writes
the v2 neutral contract without deleting legacy bytes; unknown future schemas fail closed.

## Design: lenient where churn is likely

Catalog and persisted-artifact schemas are deliberately **lenient** (`additionalProperties: true` on
deeply-nested, frequently-edited entries) so that adding a stack/profile/server/pack stays a pure
data edit without a forced schema change. They assert top-level shape and types,
plus the few genuinely-contractual fields (e.g. an org-pack component's `name` + `existing`). The
user-supplied `--config` file is intentionally **not** schema-checked here: `claude_kit.prompts`
already validates it (unknown-key rejection + flat/nested coercion + loud type errors).

Format-version fields are exact constants, not open-ended integers. A future schema therefore fails
on an older reader instead of being interpreted under obsolete semantics. Org-pack `version` remains
a pack release version (`0.1.0` today), not a schema-format field, so it is intentionally not `const: 1`.
