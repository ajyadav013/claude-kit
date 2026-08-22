# Canonical agent projection adaptations

The canonical agent tree is provider-neutral and instantiates the `AgentSpec`
contract. Claude Code and Codex consume the same definitions, but their native
agent formats expose different controls. The renderer boundary deliberately
adapts the following fields.

| Canonical semantic | Claude Code projection | Codex projection |
|---|---|---|
| `model_tier` (`fast`, `balanced`, `deep`) | Resolves to the native `model` alias. | No model is hard-coded; the active runtime selects it. |
| `permission` | Resolves to a valid `permissionMode`; external-effect roles are refused by unattended managed execution and never use bypass mode. | Resolves to native `sandbox_mode`; managed execution also fixes `approval_policy = "never"` inside that sandbox and refuses external-effect roles. |
| `capabilities` | Resolves to the exact native tool allowlist. A single file-write capability grants the host's create/edit primitives. | Browser, computer-use, app, delegation, and selected MCP controls are enabled or disabled explicitly; filesystem and shell capabilities are bounded by the native sandbox. |
| `write_scope` | The managed adapter verifies the complete tracked, untracked, and ignored path delta against the declared globs. Claude agent frontmatter has no preventative glob-scoped write field. | The native sandbox prevents writes outside the owned worktree; the managed adapter additionally verifies the complete path delta against the narrower declared globs. |
| `isolation` | Kept as role policy; the orchestrator chooses native worktree isolation when dispatching. | Kept as role policy; the controller chooses the available isolation mechanism. |
| `nested_delegation` | Delegation tools are granted only when the semantic contract requires them. | Projects native `[agents].enabled` and `features.multi_agent`; the managed coordinator owns the durable task ledger for both providers. |
| symbolic references | Resolve to `.claude/`, `CLAUDE.md`, and slash-skill locations. | Resolve to `.codex/agents`, `.agents/skills`, `AGENTS.md`, and shared `.ckit` state. |
| `workflow_tier` | Preserves the existing plugin-discovery `tier` metadata; display color is deterministically derived. | Included in developer instructions; it does not select a model. |

Two imported definitions intentionally share the logical ID
`migration-specialist`: their canonical paths retain the PostgreSQL and MongoDB
stack context, and the already-resolved `stack_dirs` selection chooses exactly
one. No stack/provider branch was added to `catalog.resolve()`.

The generated root and overlay Markdown files remain Claude plugin compatibility
artifacts. `scripts/gen_provider_payloads.py --check` fails when any is missing,
stale, or unmanaged. Codex reads canonical definitions directly, so a generated
Claude artifact can never silently become Codex's source of truth.

Managed execution deliberately distinguishes semantic authorization from technical
containment. Codex invocations use strict config, an OS-enforced read-only or
workspace-write sandbox, outbound command networking disabled, `/tmp` excluded from
writable roots, and secret-filtered child environments. Claude Code has no equivalent
portable OS-enforced command sandbox: its exact tool and permission mapping plus the
post-run path-delta check are adapted controls, while shell egress remains a documented
Preview degradation. Neither adapter attests `external.mutation`; a stage that requires
it must produce a fail-closed human stop instead of silently falling back to a weaker role.
Managed approval resumption is unsupported, so that stop cannot be converted into authorization by
a generic local evidence file.
