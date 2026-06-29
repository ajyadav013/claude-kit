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
| `org-pack.schema.json` | `templates/org/packs/<id>/pack.yaml` | `check_catalog` / CI |
| `mcp-lock.schema.json` | `.mcp.lock.json` (a project's resolved MCP lock) | `validate --strict` |
| `pipeline-snapshot.schema.json` | `.claude/state/pipeline-snapshot.json` | `validate --strict` |

## Optional dependency

Validation uses [`jsonschema`](https://pypi.org/project/jsonschema/), an **optional** dependency:

```
pip install claude-kit[schema]
```

claude-kit's runtime install stays at three dependencies (typer · jinja2 · pyyaml). When
`jsonschema` is absent, schema validation degrades to a no-op — `check_catalog` and
`validate --strict` still run their referential checks, and emit one advisory line noting the skip.

## Design: lenient where churn is likely

Catalog and persisted-artifact schemas are deliberately **lenient** (`additionalProperties: true` on
deeply-nested, frequently-edited entries) so that adding a stack/profile/server/pack stays a pure
data edit (golden rule #6) without a forced schema change. They assert top-level shape and types,
plus the few genuinely-contractual fields (e.g. an org-pack component's `name` + `existing`). The
user-supplied `--config` file is intentionally **not** schema-checked here: `claude_kit.prompts`
already validates it (unknown-key rejection + flat/nested coercion + loud type errors).
