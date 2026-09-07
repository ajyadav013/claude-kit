# Canonical agent sources

This tree is the authoritative source for every agent definition. Each Markdown
file has strict semantic frontmatter validated by `schemas/canonical-agent.schema.json`
and a provider-independent instruction body.

Layout:

- `core/<id>.md` — the 31 stack-neutral engineering roles.
- `stacks/<stack-dir>/<id>.md` — stack overlays selected through the existing catalog.
- `org/<id>.md` — organization-scope personas selected through the org catalog.

Instructions reference other components by logical URI (`agent://`, `skill://`,
`rule://`, `state://`, and related schemes). Runtime adapters resolve those URIs
to native destinations. Generated payload files must never be edited directly;
run `scripts/gen_provider_payloads.py`, or use its `--check` mode in verification.
