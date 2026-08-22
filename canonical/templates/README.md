# Canonical text templates

These provider-neutral bodies cover project instructions, stack and continuity
seeds, memory and artifact templates, installed READMEs, exports, and organization
pack text/manifests. Same-name YAML sidecars record stable ids, physical compatibility
destinations, formats, symbolic references, and every provider adapter placeholder.

Run `python3 scripts/gen_template_payloads.py` to render the current Claude-compatible
`templates/` files, or add `--check` to detect drift. Hook settings/scripts and all
agent, skill, and rule payloads are intentionally owned by their separate generators.

The compatibility renderer preserves the legacy host's transcript-capture paragraph and
bounded unattended-loop instructions. Those two features are capability-dependent: a
provider adapter that cannot run background capture or the loop must mark them unsupported
or omit those paragraphs. The exported workflow guide is deliberately phrased in terms of
available named delegation instead of assuming every non-legacy host is single-agent.
