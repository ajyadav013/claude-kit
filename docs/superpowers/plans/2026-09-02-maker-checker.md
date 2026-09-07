# Configurable Maker–Checker — Implementation Plan

**Date:** 2026-09-02 · **Branch:** `codex/maker-checker` · **Design:**
[`../specs/2026-09-02-maker-checker-design.md`](../specs/2026-09-02-maker-checker-design.md)

## Delivery slices

- [x] **Configuration contract**
  - Acceptance: schema-v3 manifests round-trip an optional typed maker/reviewer policy; v1/v2
    migrate disabled; invalid providers/models/revision budgets fail before writes.
  - Verify: focused model and prompt tests.
  - Files: `models.py`, `prompts.py`, runtime scaffold/upgrader preservation, related tests.

- [x] **Install and configure-anytime UX**
  - Acceptance: interactive init is opt-in; config YAML works non-interactively; `show`,
    `configure`, `disable`, and `probe` mutate only the shared `.ckit` state transactionally.
  - Verify: CLI tests for Claude-only, Codex-only, both, defaults/EOF, and transition refusal.
  - Files: `cli.py`, prompt/runtime lifecycle helpers, CLI tests and docs.

- [x] **Provider-neutral skill with native Codex projection**
  - Acceptance: one canonical explicit skill generates Claude `/maker-checker` and Codex
    `$maker-checker` discovery surfaces, including Codex explicit-only policy metadata.
  - Verify: canonical schema/reference/profile and generated-payload checks.
  - Files: canonical skill/references, catalog/profile metadata, render mappings, generated payloads,
    skill tests.

- [x] **Bound dispatch bindings**
  - Acceptance: dispatches carry maker/reviewer slot and requested model; Claude and Codex adapters
    inject exact model overrides as safe argv elements; a routed dispatcher preserves ownership for
    all six lifecycle operations.
  - Verify: dispatch/process-adapter unit tests including same-provider and cross-provider cases.
  - Files: `dispatch.py`, `process_dispatch.py`, routed-dispatch module/tests.

- [x] **Authoritative maker–checker loop**
  - Acceptance: frozen contract and binding digests; fresh read-only reviewer; typed PASS/FAIL;
    semantic FAIL creates a new maker iteration; unchanged artifacts and stale evidence fail closed;
    bounded exhaustion becomes a human stop.
  - Verify: first-pass PASS, revise/PASS, exhausted, disagreement, timeout/cancel, and resume tests.
  - Files: coordinator/evidence/pipeline modules, schema, tests.

- [x] **Cross-host documentation and conformance**
  - Acceptance: install/CLI/architecture/runtime-support docs describe both native invocations and
    report Codex Preview limitations precisely; doctor surfaces configuration and capability gaps.
  - Verify: all repository deterministic checks plus Claude, Codex, and both projection smokes.

## Boundaries

- Keep runtime and execution policy outside `Selection` and `catalog.resolve()`.
- Keep one `.ckit` control plane; never persist provider-local ledgers or credentials.
- Never hand-edit generated provider payloads or frozen 0.83 fixtures.
- Do not make coding available through an uncontained write/shell subprocess. Use a validated patch
  channel or report the capability Unsupported until containment is proven.
- Do not publish, merge, tag, upload, or broaden external-action authority.
