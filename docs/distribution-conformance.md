# Distribution conformance

Claude Code and Codex consume one repository payload, so a release is conformant only when the
source checkout, wheel, and sdist describe the same logical kit.

## Archive contract

`tests/test_distribution_conformance.py` builds a staged source snapshot twice with a fixed
`SOURCE_DATE_EPOCH` and verifies that each repeated wheel and sdist is byte-identical to its
counterpart. It also requires:

- one `AGENTS.md` and one copy of each Claude/Codex plugin and marketplace manifest;
- the complete generated `providers/codex/claude-kit` package root, including its 126 skills,
  native manifest, 16-handler hook document, and exact adapted script inventory;
- byte-for-byte Python package and payload parity between the source snapshot, wheel, and sdist;
- package, module, and provider-manifest version parity;
- the `claude-kit`, `ckit`, and `claude-sdlc` console aliases;
- exclusion of local `.codex`, cache, virtual-environment, dependency, build, bytecode, and
  `.DS_Store` paths, including deliberately injected machine-local fixtures.

The isolated artifact smoke installs the wheel and sdist into fresh virtual environments and runs
native `init --runtime claude|codex|both`, strict validation, and all three console aliases. The
Codex and dual cases enable `CKIT_EXPERIMENTAL` only inside the smoke process.
Run it locally with
`CKIT_RUN_DISTRIBUTION_SMOKE=1 pytest -q tests/test_distribution_conformance.py`.

CI's `distribution conformance + verified build` job enforces the archive inventory before it
uploads the verified artifacts. The exact `wheel-smoke-claude`, `wheel-smoke-codex`, and
`wheel-smoke-both` PR checks install and exercise that wheel; parallel `sdist-smoke-*` entries retain
the same three-runtime coverage for the source distribution.

## Native plugin-host boundary

`tests/test_plugin_host_smoke.py` always checks the deterministic manifest selectors, versions,
local sources, and installation policies. When a supported host executable is installed, every
command uses a staged plugin plus temporary `HOME`, `XDG_CONFIG_HOME`, `CLAUDE_CONFIG_DIR`, and
`CODEX_HOME`; known host credential variables are removed, and the test never reads or mutates the
developer's real host configuration.

| Host | Automated native coverage | Deliberate boundary |
|---|---|---|
| Claude Code | strict validation; marketplace add/list/remove; plugin install/list/uninstall | None for this non-credentialed local plugin lifecycle. |
| Codex | official plugin-creator validation of source, staged, and installed roots; marketplace add/list/remove; plugin add/remove; app-server discovery of exactly 126 enabled skills and 16 native hook handlers with zero loader errors | The committed `ON_USE` policy defers provider/tool credentials until use; the smoke does not invoke a credentialed component or approve hook execution. |

The pinned Claude Code and Codex compatibility matrices run these safe native checks in CI. If a
host CLI is absent or predates the required plugin commands, the native test skips while the
deterministic manifest and archive checks remain mandatory. Credentialed component invocation and
interactive host trust prompts remain a manual release check.
