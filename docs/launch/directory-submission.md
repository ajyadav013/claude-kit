# Plugin Directory Submission Checklist

This document outlines the steps for submitting claude-kit to the Anthropic plugin directory/marketplace, plus install-today instructions for users.

## Pre-Submission Validation

The plugin manifests (`.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`) are already valid and ready for submission. Before submitting, run the validation commands to confirm:

```bash
# Standard validation
claude plugin validate .

# Strict validation (checks optional/recommended fields)
claude plugin validate . --strict
```

Fix any errors. Warnings from `--strict` are optional improvements, not blockers.

## Optional Manifest Hygiene

These are non-blocking improvements that may be addressed before or after submission:

1. **Owner schema alignment**: The `.claude-plugin/marketplace.json` currently uses `{name, url}` for the owner field. The documented schema is `{name, email}`. The `url` field is non-standard and may trigger a warning under `--strict`. Consider switching to `{name, email}` for consistency with the documented schema.

2. **Version duplication**: The version appears in both `plugin.json` (authoritative) and the marketplace entry. This is expected but note that `plugin.json` is the source of truth.

## Install Today (No Directory Required)

Users can install claude-kit immediately without waiting for directory listing:

```bash
# Add the GitHub marketplace
/plugin marketplace add ajyadav013/claude-kit

# Install the plugin
/plugin install claude-kit@claude-kit
```

Use this snippet in the README, release notes, or social posts.

## Submission Paths

Anthropic reviews third-party submissions before they land in the public community marketplace (`claude-community`). Submit via one of the in-app forms below. The form you can use depends on whether you have a Team/Enterprise organization.

### Solo / Individual Developers

Submit via the Console plugin submission form:

- URL: [platform.claude.com/plugins/submit](https://platform.claude.com/plugins/submit)
- Available to individual authors who are not part of a Team or Enterprise organization

### Organizations (Team / Enterprise)

Submit via the claude.ai submission form:

- URL: [claude.ai/admin-settings/directory/submissions/plugins/new](https://claude.ai/admin-settings/directory/submissions/plugins/new)
- Requires a Claude Team or Enterprise organization plus directory management access (organization Owners have this by default)

### Official / Curated Marketplace

The official curated marketplace (`claude-plugins-official`) is curated by Anthropic at its discretion. There is no open application process, and the submission forms above do not add plugins to the official marketplace.

## Reference Documentation

Before submitting, **re-check the live documentation** at the URLs below. Plugin requirements and submission processes may change:

- Plugin development guide: [code.claude.com/docs/en/plugins](https://code.claude.com/docs/en/plugins)
- Plugin marketplaces: [code.claude.com/docs/en/plugin-marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)
- Plugin reference: [code.claude.com/docs/en/plugins-reference](https://code.claude.com/docs/en/plugins-reference)

## Directory Review Self-Audit

Directory reviewers apply pass/fail criteria a submitter can run against themselves first. Three
that decide outcomes:

1. **Description-matches-behavior (the surprise test).** For every hook, command, and skill: would
   a user who read only its description be *surprised* by anything it actually does? Any surprise
   is a fix-before-submitting.
2. **Undisclosed outbound calls = automatic fail.** Every network touch (direct or via a spawned
   tool) must be disclosed in the component's description *and* have an opt-out.
3. **The whole shipped payload is in scope — including directories the plugin doesn't load.**
   A git-source install clones everything (`scripts/`, `templates/`, `catalog/`, `examples/`), so
   the audit covers the full tree, not just auto-discovered components.

### First-party hook audit (run against this kit's own registry)

All 23 project-scaffold registry hooks and the explicit plugin-only guard are listed in the
reviewer's format — `EVENT:hook — gated|advisory — network`. **gated** = can deny an action or
request a guarded Stop continuation; **advisory** = warn-or-context only. Regenerate this table when
the registry changes (`src/claude_kit/hooks.py` is the source of truth; `gen_hooks.py --check` pins
the generated configs).

| Hook | Event | Mode | Network | In plugin hooks.json |
|------|-------|------|---------|----------------------|
| load-continuity | SessionStart | advisory | no | yes |
| load-learnings | SessionStart | advisory | no | yes |
| load-autonomy | SessionStart | advisory | no | yes |
| capture-learnings-catchup | SessionStart | advisory | **indirect in Claude mode** — selected-provider model job; Codex historical catch-up no-ops; disclosed, opt-out `CLAUDE_KIT_NO_AUTOCAPTURE=1` | no |
| guard-rm-rf | PreToolUse | **gated** (inline) | no | yes |
| guard-push-main | PreToolUse | **gated** | no | yes |
| guard-destructive-git | PreToolUse | **gated** | no | yes |
| protect-secrets | PreToolUse | **gated** (inline) | no | yes |
| guard-commit-secrets | PreToolUse | **gated** | no | yes |
| guard-kubectl-delete | PreToolUse | **gated** | no | yes — plugin only |
| validate-settings | PreToolUse | **gated** | no | yes |
| warn-shared-modules | PreToolUse | advisory | no | yes |
| warn-llm-io | PreToolUse | advisory | no | yes |
| warn-sensitive-files | PreToolUse | advisory | no | yes |
| warn-large-edits | PreToolUse | advisory | no | no |
| validate-frontmatter | PreToolUse | advisory | no | no |
| warn-missing-tests | PostToolUse | advisory | no | no |
| audit-log | PostToolUse | advisory | no | no |
| lint-fix | Stop | **gated once** (may request one guarded continuation after running the project linter) | no | yes |
| type-check | Stop | **gated once** (may request one guarded continuation after running the project type checker) | no | yes |
| verify-continuity-writeback | Stop | **gated once** (requests one guarded continuation when continuity is stale) | no | yes |
| capture-learnings-stop | Stop | advisory | indirect — selected-provider classifier + opt-out as above | no |
| capture-ticket-telemetry | Stop | advisory | no — local transcript metadata only; Codex no-ops | no |
| capture-learnings | SessionEnd | advisory | indirect — selected-provider classifier + opt-out as above | no |

**Audit result:** the project-scaffold registry has 23 hooks. The static plugin's `hooks.json` has
exactly 16 handlers: 15 registry hooks plus the plugin-only `guard-kubectl-delete`; it contains no
learning-capture trigger. The remaining registry hooks are profile-selected project hooks or, for
the capture family, explicit `capture_mode` selections. Learning capture is the only behavior
family that touches the network indirectly through a selected-provider classifier; it is disclosed
in the init interview, surfaced by `doctor`, and opt-out via `CLAUDE_KIT_NO_AUTOCAPTURE=1`. No hook
makes a direct outbound call. Safety guards are deterministic and have no data egress; the local
quality Stop hooks may run the project's linter or type checker and request one guarded
continuation. This passes criteria 1–3 above as of the audit date; re-run after any hook change.

## Owner Submission Checklist

- [ ] Run `claude plugin validate .` and `claude plugin validate . --strict`
- [ ] Fix any validation errors (warnings are optional)
- [ ] Re-run the Directory Review Self-Audit above (hook table current, no undisclosed network, no description surprises)
- [ ] Verify the live submission form and documentation links above
- [ ] Consider the optional manifest hygiene items (not required)
- [ ] Choose submission path: solo (platform.claude.com) or organization (claude.ai)
- [ ] Submit the plugin
- [ ] Update installation instructions once directory listing is live (if different from the GitHub marketplace install)

---

**License**: MIT © Arjunsingh Yadav  
**Repository**: [github.com/ajyadav013/claude-kit](https://github.com/ajyadav013/claude-kit)  
**PyPI**: [pypi.org/project/claude-code-kit](https://pypi.org/project/claude-code-kit)
