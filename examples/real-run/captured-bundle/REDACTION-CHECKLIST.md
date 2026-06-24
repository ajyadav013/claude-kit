# Redaction checklist — finish before publishing this bundle

This bundle was copied verbatim from a real project. The automated scan only catches *generic*
secret shapes. Before you publish it (e.g. into `examples/` or a blog post), manually confirm:

- [ ] No company / team / internal-service / repo / registry / cluster / namespace / project-id names
- [ ] No internal hostnames, IPs, URLs, or cloud project identifiers
- [ ] No customer / personal data in the spec, diff, or verdict log
- [ ] No secret VALUES (keys, tokens, passwords, connection strings) — the scan flags shapes, not all
- [ ] `changes.diff` reviewed line-by-line (it contains your actual source)
- [ ] `continuity.md` reviewed (it may quote commands, paths, and findings verbatim)

Tip: keep a private copy, publish a scrubbed copy. Replace real identifiers with neutral
placeholders (`acme`, `example.com`, `service-a`) rather than deleting context.
