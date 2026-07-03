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

## Owner Submission Checklist

- [ ] Run `claude plugin validate .` and `claude plugin validate . --strict`
- [ ] Fix any validation errors (warnings are optional)
- [ ] Verify the live submission form and documentation links above
- [ ] Consider the optional manifest hygiene items (not required)
- [ ] Choose submission path: solo (platform.claude.com) or organization (claude.ai)
- [ ] Submit the plugin
- [ ] Update installation instructions once directory listing is live (if different from the GitHub marketplace install)

---

**License**: MIT © Arjunsingh Yadav  
**Repository**: [github.com/ajyadav013/claude-kit](https://github.com/ajyadav013/claude-kit)  
**PyPI**: [pypi.org/project/claude-code-kit](https://pypi.org/project/claude-code-kit)
