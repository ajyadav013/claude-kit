# The road to 1.0

claude-kit is at **v0.57.0** and carries the **Development Status :: 4 - Beta** classifier. That Beta label is intentional — it stays until the gaps listed below are addressed. This document is the anti-sycophancy roadmap: an honest inventory of what stands between the current release and a 1.0.

## Why we honestly stay Beta

A 1.0 release signals stability, production-readiness, and API guarantees. claude-kit works today — the `/sdlc` pipeline drives real features through quality gates, the devils-advocate agent has caught reproducible defects that unanimous reviews missed (see [`examples/real-run/`](../../examples/real-run/)), and the trust moat (gates pass only on cited, real command output) is operational. But the project is not yet at the level of maturity where breaking changes are prohibitively expensive, the enforcement boundary is clearly delineated, and the common stacks are all selectable. The Beta classifier is accurate.

This document catalogues the gaps, explains why each matters, and defines what "done" looks like. There are no invented timelines — these are concrete, verifiable blockers.

---

## The gaps

### 1. Stack coverage

**The gap:** Only **React**, **Python/FastAPI**, **Go/net-http**, **PostgreSQL**, and **MongoDB** have shipped overlay content (rules, agents, skills) and are selectable. **Vue**, **Svelte**, **Django**, and **Node/Express** are listed in `catalog/stacks.yaml` with `status: planned` — they appear as "coming soon" but cannot be chosen; no overlay rules exist under `templates/stacks/` for them.

**Why it matters:** A stack-agnostic scaffolder that only supports five stacks is misleading. The current catalog is honest (planned entries are marked and gates block their selection), but a 1.0 should either ship the common stacks or prune the planned list to reflect realistic scope.

**What "done" looks like:**

- The standard web/API combinations (React/Vue/Svelte × FastAPI/Django/Express × Postgres/MongoDB) are selectable and have overlay rules that pass the `pytest` profile × stack × scope matrix, OR
- The planned entries are removed from the catalog with a documented rationale (e.g., "focused on React + Python/Go; other frameworks via generic core rules only"), OR
- A documented hybrid: React + Python/Go + Postgres/MongoDB are first-class (full overlays); Vue/Svelte/Django/Express remain planned and are explicitly listed as future additions with a public tracker.

Current status: **5 of 9** catalogued stacks are live.

### 2. Enforcement honesty: agent protocols vs. mechanical gates

**The gap:** Most quality gates are **agent protocols** that the model self-verifies, not mechanical enforcement. A reviewer agent returns a verdict; the pipeline script checks the verdict's structure and blocks on Critical/High/Medium findings, but it does not independently re-run the checks. Only the **hook scripts** (block destructive git, force-push, `kubectl delete`, secret-bearing commits) are host-enforced — and even those are best-effort word/regex matchers, not a sandbox (see [`docs/KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md)).

The kit is honest about this: the `quality-gates.md` rule states that a gate passes only when the agent verdict meets the criteria and cites real command output, and that a fabricated, assumed, or partial-output verdict is itself a Critical finding. The deterministic pipeline state enforces verdict structure + sequential gate ordering, and the devils-advocate adversarially re-verifies unanimous passes. That anti-sycophancy loop works ([`examples/real-run/`](../../examples/real-run/) demonstrates it), but it is still model-driven verification, not an independent mechanical check.

**Why it matters:** Calling something a "quality gate" implies a hard, unevadable constraint. Agent-based verification with adversarial checks catches real bugs — but it is a different trust model than, for example, a CI script that runs `pytest` and parses the exit code. The current design is honest, but a 1.0 should draw a clearer boundary and expand mechanical enforcement where feasible.

**What "done" looks like:**

- A documented **trust boundary** that states which gates are agent-verified (with adversarial review) and which are mechanically enforced.
- Where practical, **more deterministic checks**:
  - Parse actual test runner output (exit codes, JUnit XML, coverage JSON) instead of relying solely on agent verdict.
  - Hook-level enforcement for more destructive operations (if feasible without becoming a sandbox).
  - Clearer "verified by devils-advocate adversarial review" labels on agent-protocol gates.
- The `quality-gates.md` rule and `README.md` carry an explicit "Enforcement model" section that does not overclaim.

Current status: deterministic state file + hook scripts + adversarial review loop. No independent test-runner parsing yet.

### 3. Hook portability: POSIX shell + jq requirement

**The gap:** The guard hooks (`guard-destructive-git`, `guard-kubectl-delete`, `guard-push-main`, `guard-secrets`, plus the advisory `warn-*` hooks) require a **POSIX shell** and **`jq`**. Without them they **silently degrade to no-ops** — the agents, rules, and skills still work, but the deterministic guards do nothing. On Windows outside WSL/Git Bash, most hooks are non-functional. The `claude-kit doctor` command detects this and warns; `init` logs which hooks succeeded; but the current design assumes a Unix-like environment.

**Why it matters:** A cross-platform CLI that only guards on macOS/Linux is a portability gap. The hooks are explicitly "convenience guardrails, not a security boundary" ([`docs/KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md)), but even convenience guardrails should work portably or fail loudly.

**What "done" looks like:**

- The `doctor` detection is comprehensive (checks shell, `jq`, and emits actionable fix steps).
- `init` warns prominently when hooks cannot be installed (not just a debug log line).
- Where practical, **improve portability**:
  - Pure-Python guard equivalents for the most critical hooks (e.g., `guard-destructive-git`, `guard-secrets`), or
  - A bundled minimal `jq` substitute for the hook subset (stateless JSON path extraction only).
- A documented "Supported environments" table in the README that states POSIX + `jq` are required for full guard functionality, and lists tested platforms (macOS, Linux, WSL2, Git Bash).

Current status: doctor-detected, fails silently without `jq`. No Windows-native guards.

### 4. Evidence base: one captured run proves the loop; 1.0 wants more

**The gap:** The [`examples/real-run/`](../../examples/real-run/) directory contains a **genuine harness-captured `/sdlc` run** (Go/net-http, DELETE `/tasks/{id}` feature, standard profile, 7 tests, 85.2% coverage, `-race` clean, devils-advocate caught a Medium bug over raw TCP). It is **not** synthetic — it is the captured output of `scripts/capture-sdlc-run.sh`. This demonstrates the defect loop and anti-sycophancy moat on real code.

**One real run** is evidence; a 1.0 should have **more**: different stacks (React frontend + FastAPI backend, MongoDB), different profiles (lean, enterprise), different scopes (team, organization), and both successful passes and caught defects.

**Why it matters:** A single captured run is a proof of concept. Multiple runs across stacks/profiles/scopes show the pipeline generalizes and is not hand-tuned for one case.

**What "done" looks like:**

- At least **three captured runs** in `examples/`:
  1. The existing Go/net-http run (backend-only, standard profile, caught defect).
  2. A **React + FastAPI** full-stack feature (lean profile, clean pass).
  3. A **PostgreSQL migration** or **MongoDB schema change** (demonstrates DB overlay agents, enterprise profile).
- Each run follows the same harness capture process: `captured-bundle/`, `run-artifacts/`, terminal recording, README with provenance.
- A `examples/README.md` index that lists each run and links to the capture script.

Current status: **1 of 3** runs captured.

### 5. Editor export fidelity: Cursor / AGENTS.md / Copilot limitations

**The gap:** `claude-kit export` projects the configuration into `.cursor/rules/`, `AGENTS.md`, and `.github/copilot-instructions.md` for use in Cursor, VS Code, and GitHub Copilot. The **standards** (rules, charter, stack overlays, MCP servers) carry over; the **enforced gates + reviewer subagents** do not. Those editors run a single agent, so the multi-agent review panel, parallel security scanners, and automated defect loop (blocks on unproven verdict) become a **self-check checklist** — guidance, not enforcement.

The exporter is **honest about this**: the generated charter carries a fidelity note stating that the enforced gates, reviewer subagents, and automated defect loop depend on Claude Code's multi-agent runtime and cannot be reproduced under a single-agent editor. (See [`docs/cursor-export.md`](../cursor-export.md).)

**Why it matters:** A teammate who reads the exported `AGENTS.md` or `.cursor/rules/` sees the standards and workflow, but does not get the adversarial review loop. That is acceptable — the export is a **projection**, not a second implementation — but it is a fidelity gap relative to Claude Code.

**What "done" looks like:**

- Keep the current honest fidelity note in the generated charter (no change).
- If Cursor or other editors gain multi-agent capabilities (subagent spawn, parallel agents, structured output parsing), expand the export to use those features.
- Document the fidelity table in `docs/cursor-export.md` (already done) and cross-reference it from the README.

Current status: export works; fidelity gap is documented. No expansion possible until those editors support multi-agent workflows.

### 6. API stability: catalog schema, CLI flags, file layout

**The gap:** The 0.x series means **the catalog schema, CLI flags, and file layout can still change**. The catalog has already evolved in ways that would break a hard 1.0 promise — for example, `catalog/profiles.yaml` composes profiles with an `inherit:` field, `catalog/org.yaml` discriminates reused vs. new pack roles with an `existing:` field, and the installed `.claude/config/init-options.json` manifest carries a `schema_version` that upgrade logic reads. These are living structures, not frozen ones.

`claude-kit upgrade` already preserves user edits (three-way merge on `CLAUDE.md`, skip user-modified files) and is convergent (re-run finishes an interrupted upgrade). But the catalog schema is not frozen, and a breaking change to `stacks.yaml` or `profiles.yaml` may require a manual migration.

**Why it matters:** A 1.0 API stability guarantee means the catalog schema is frozen and a breaking change triggers a 2.0. Before 1.0, the schema should be right — not merely workable.

**What "done" looks like:**

- A documented **catalog schema stability guarantee**: the top-level structure (`stacks.yaml`, `profiles.yaml`, `mcp.yaml`, `org.yaml`) is frozen; new fields may be added (backward-compatible), but existing fields cannot be renamed or have their semantics changed without a major version bump.
- An explicit **upgrade path policy**: `claude-kit upgrade` handles schema migrations within a major version; a major bump may require a manual migration (scripted where feasible).
- The `init-options.json` manifest already carries `schema_version` (currently `1`); the documented policy states that a schema change bumps it and gates the upgrade logic, and that the catalog files gain the same treatment.

Current status: `upgrade` preserves edits and is convergent; the `init-options.json` manifest is versioned (`schema_version = 1`), but the catalog schema itself is not frozen.

### 7. Test and CI surface: keep the matrix green and grow it as stacks land

**The gap:** The `pytest` suite runs a **profile × stack × scope self-test matrix** — it scaffolds into temp directories, asserts the no-Docker invariant, checks profile subset inclusion, validates MCP gating, and verifies upgrade safety. The test surface is solid; it needs to **grow as stacks are added** (currently React, Python/FastAPI, Go/net-http, Postgres, Mongo are tested; Vue/Svelte/Django/Express will need tests when they ship).

**Why it matters:** A green CI suite that only tests five stacks is insufficient when the catalog advertises nine. Each new stack overlay must be mechanically verified to not leak Docker/app-code and to compose with all three profiles.

**What "done" looks like:**

- Every **selectable stack** (with shipped overlay content) is in the pytest matrix.
- CI enforces:
  - The no-Docker invariant (grep the scaffolded project).
  - Profile subset inclusion (lean ⊂ standard ⊂ enterprise).
  - MCP gating (no `.mcp.json` when `--no-mcp`).
  - Upgrade convergence (run `upgrade` twice; second is a no-op).
- A `CONTRIBUTING.md` note that states: "Adding a stack requires a pytest case; CI will fail without it."

Current status: the pytest self-test matrix (`tests/_helpers.py::live_matrix`) sweeps every live stack combination — React × {FastAPI, Go/net-http} × {Postgres, MongoDB} — across all three profiles (lean/standard/enterprise) and the team + organization scopes, install-and-validating each. All five live stacks are exercised. CI is green. No Vue/Svelte/Django/Express tests (those stacks are planned but not shipped).

---

## What 1.0 explicitly does NOT promise

Being honest about scope is as important as closing gaps. A 1.0 release will **not**:

- **Vendor or audit MCP servers.** The `catalog/mcp.yaml` registry **references** third-party servers (pinned to exact versions). A scheduled freshness check flags stale pins, but bumping a pin is a deliberate, reviewed action. Treat each server as third-party software you choose to run. See [`docs/KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).
- **Become a sandbox or security product.** The guard hooks are **convenience guardrails** that stop accidental agent mistakes, not a hardened security boundary. A motivated operator who crafts obfuscated commands (env-var indirection, `python -c`, `find -delete`) can evade them. They require a POSIX shell + `jq` and no-op on Windows outside WSL/Git Bash. See [`docs/KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).
- **Support every stack.** claude-kit is stack-agnostic (the core payload has no framework assumptions), but overlay rules exist only for selected stacks. A 1.0 may ship React/Vue/Svelte + Python/Go/Node + Postgres/MongoDB; it will not ship overlays for every language/framework/database. Projects outside the catalog use the generic core rules.
- **Auto-migrate breaking changes.** Within a major version, `claude-kit upgrade` handles schema changes. A 2.0 may require a manual migration (scripted where feasible). That is standard semver.

---

## How to help

Contributions that close the above gaps are welcome. High-value areas:

1. **Ship the planned stacks** (Vue, Svelte, Django, Node/Express) — overlay rules + pytest case. See [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
2. **Capture more real runs** across stacks/profiles/scopes. Run `/sdlc` on a real feature, then `scripts/capture-sdlc-run.sh`. Document the provenance (stack, profile, verdict, defect if any). See [`docs/capture-a-real-run.md`](../capture-a-real-run.md).
3. **Improve hook portability** — pure-Python guard equivalents or a bundled minimal JSON parser for Windows.
4. **Expand mechanical enforcement** — parse test-runner output (exit codes, JUnit XML, coverage JSON) and merge it with agent verdicts.
5. **Strengthen the API stability guarantee** — document the catalog schema stability promise and extend the existing `init-options.json` `schema_version` treatment to the catalog files.

Seed issues tracking these gaps:

- [#TBD: Ship Vue/Svelte/Django/Express overlays](https://github.com/ajyadav013/claude-kit/issues)
- [#TBD: Capture three real runs (React+FastAPI, Postgres migration, MongoDB schema)](https://github.com/ajyadav013/claude-kit/issues)
- [#TBD: Improve hook portability (Windows, pure-Python guards)](https://github.com/ajyadav013/claude-kit/issues)
- [#TBD: Mechanical gate enforcement (test-runner parsing)](https://github.com/ajyadav013/claude-kit/issues)
- [#TBD: Catalog schema stability guarantee](https://github.com/ajyadav013/claude-kit/issues)

(These issue links will be populated as the launch tasks progress. Check [the Issues tab](https://github.com/ajyadav013/claude-kit/issues) for live status.)

Before opening a PR, please read [`CONTRIBUTING.md`](../../CONTRIBUTING.md). The golden rules: keep the core stack-agnostic, never ship Docker/app-code, reference rules by their canonical `.claude/rules/` path, and extend via the catalog (not code).

---

The Development Status classifier will remain **4 - Beta** until these gaps are addressed. That is the honest state of the project. When the above checklist is complete — or the scope is explicitly reduced and documented — we will ship 1.0.
