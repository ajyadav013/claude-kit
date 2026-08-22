# Canonical rules

This tree is the provider-neutral source of truth for engineering rules. Each
Markdown body has a same-name YAML sidecar containing its stable logical id,
strength, selection applicability, path globs, and complete symbolic-reference
inventory.

Edit these sources, then run `python3 scripts/gen_rule_payloads.py`. The root
`rules/` tree and stack/org rule trees are generated Claude compatibility output.
Use `python3 scripts/gen_rule_payloads.py --check` in validation workflows.

Provider-owned path globs use `@agents/`, `@skills/`, `@memory/`, and `@runtime/`.
Bodies use component URIs such as `rule://testing` and explicit
`{{ provider.* }}` adapter placeholders where a model, tool, executable, or path
has no provider-independent spelling.
