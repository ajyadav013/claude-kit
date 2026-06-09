# Changelog

All notable changes to claude-kit are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses
[semantic versioning](https://semver.org/).

## [0.4.0] — 2026-06-09

Adds the **agent-operation layer** distilled from *Agentic Design Patterns* (A. Gulli). A full
cross-map of the book's 21 patterns against the kit found most already covered by existing rules,
agents, skills, and the orchestration model; the genuine gap was how the **agents themselves** reason,
stay safe, and recover (as opposed to how the **product** they build is secured and tested). Five new
always-on, stack-agnostic rules fill it. No application code, no Docker, no catalog change — core
rules ship to every profile.

### Added
- **Five agent-operation rules** (`rules/`, installed in every profile):
  - `reasoning-techniques.md` — Chain-of-Thought, ReAct (reason→act→observe), Tree-of-Thought /
    self-consistency, step-back, extended-thinking effort budget, and resource-aware model-tier
    selection.
  - `agent-guardrails.md` — treat fetched/tool/file content as untrusted (prompt-injection defense),
    validate own output before handoff, and tool least-privilege. Distinct from the product-security
    agents/skills.
  - `agent-resilience.md` — bounded retries with backoff, fallback, circuit-breaker, graceful
    degradation, idempotency, and checkpointing via CONTINUITY.
  - `goal-setting-and-monitoring.md` — measurable/verifiable success criteria, progress monitoring,
    and prioritization (urgency · importance · dependencies) with dynamic re-prioritization.
  - `human-in-the-loop.md` — the consolidated set of decision points where the pipeline must pause for
    a human, plus the escalation protocol.
- **`docs/agentic-patterns.md`** — a coverage map of all 21 patterns + Appendix A onto the kit, and a
  record of what was deliberately left out (vector RAG, exploration/discovery, redundant rules) and why.

### Changed
- `rules/agent-memory.md` — added the **working / episodic / semantic / procedural** memory taxonomy,
  mapped onto the existing CONTINUITY + `agent-memory/` split.
- `rules/mandatory-workflow.md` — added an "Agent operating disciplines" pointer to the five new rules
  and linked the "When to STOP and ask the user" section to `human-in-the-loop.md`.
- Docs now reference an **18-file** rule set (was 13) — `README.md`, `CLAUDE.md`, `docs/architecture.md`.

## [0.3.0] — 2026-06-08

Reshapes claude-kit into a **Cookiecutter-style scaffolder for the Claude Code _configuration_
only** — catalog-driven, profile-aware, and with no application code or Docker anywhere. The
`claude-kit new` app generator from 0.2.0 is **removed**; the FastAPI/React knowledge it carried is
preserved as catalog **overlay rules**.

### Added
- **Catalog-driven extensibility** (`catalog/{stacks,profiles,mcp}.yaml`) — adding a frontend
  framework, backend language/framework, database, profile, or MCP server is a **data change** plus a
  `templates/stacks/<dir>/` folder, never a code change. Live: React · Python/FastAPI ·
  PostgreSQL/MongoDB; Vue/Svelte/Django/Express are listed as `planned`.
- **Ordered `init` prompts** — target path, frontend framework + language, backend language +
  framework, database, SDLC profile, and optional MCP integrations; with existing-`.claude/` handling
  (**merge / overwrite / backup / abort**).
- **SDLC profiles** — `lean ⊊ standard ⊊ enterprise` select which agents, skills, hooks, and quality
  gates are activated (composed via `inherit:` + an `all` token).
- **`/sdlc` skill** — the single, profile-aware pipeline entrypoint; it reads the resolved gate set
  from `.claude/config/stack-catalog.snapshot.yaml` and delegates to the `orchestrator`.
- **Lifecycle commands** — `validate`, `doctor`, `diff`, `upgrade [--force]`, `list-options`, plus a
  `claude-sdlc` alias entry point. Upgrades are checksum-tracked via
  `.claude/config/init-options.json` (per-file `owner`: kit / overlay / user-editable), so kit files
  refresh while user edits are protected with `.claude-kit` sidecars and changed/removed files are
  backed up.
- **Optional MCP** — selecting integrations writes a project-root `.mcp.json` (env-placeholder
  config only, never credentials); nothing is written if none are selected.
- **New core agents** — `story-planner` (spec → ordered, parallelizable stories) and
  `acceptance-reviewer` (delivery vs. acceptance criteria before the human gate). A lightweight
  `tier:` field (orchestrator / stage-lead / specialist / review) is recorded on every agent.
- **Database overlay agents** — `postgres-specialist`, `mongodb-specialist`, and a per-database
  `migration-specialist`, installed only for the selected database.
- **Artifact templates** in `.claude/templates/` (feature-spec, ADR, test-plan, security-review,
  release-plan, runbook) and a generated `README.claude-sdlc.md`.

### Changed
- **No Docker, no app code** — the kit installs configuration only. `devops-engineer` is rewritten to
  be **container-optional** (CI/build/release/migrations/health for any runtime) and Docker is
  scrubbed from the agnostic core.
- Tooling adopted: **Typer** (CLI), **Jinja2** (`StrictUndefined`, `.tmpl`-gated rendering, `dot__`
  dotfile convention), and **PyYAML** (catalog).
- `/claude-kit:init` now prefers the pip CLI when on PATH and falls back to a thin `scripts/init.sh`;
  `/claude-kit:sdlc` delegates to the `sdlc` skill.

### Removed
- **`claude-kit new`** app generator, the `/claude-kit:new` command, `scripts/new.py`, and all
  generated application source + Docker assets under `templates/stacks/*/files/`.

## [0.2.0] — 2026-06-08

Adds a cookiecutter-style **project generator** alongside the existing config scaffolder.

### Added
- **`claude-kit new`** (and the **`/claude-kit:new`** plugin command) — generate a batteries-included
  monorepo with the SDLC config baked in. Interactive prompts (or `--no-input`) for the stack;
  `--backend`, `--frontend`, `--db`, `--here`, `--force` flags.
- **Stack registry** under `templates/stacks/` — each stack is a folder with a `stack.json`; adding a
  stack is a data change, not a code change. Ships **`python-fastapi`** (async SQLAlchemy 2.0 +
  Alembic + Postgres, layered router→service→repository→model, pytest-asyncio) and **`react`**
  (TypeScript + Vite + Vitest/RTL, typed Axios client, feature folders).
- **Generated app is batteries-included**: `docker compose up` (db + backend + frontend, zero local
  installs) *and* a `Makefile` for native dev; a worked **items** vertical slice with tests on both
  sides; an initial Alembic migration so `alembic upgrade head` works out of the box.
- **Stack overlay rules** — `fastapi-patterns.md` and `react-patterns.md` are installed into
  `.claude/rules/` only for the chosen stacks, and the generated `CLAUDE.md` "Project-specific rules"
  section is filled with the concrete commands and layout, so the agents follow the stack.
- **`docs/agents.md`** — a dedicated guide to using the agents.
- Zero-dependency template renderer (`*.tmpl` substitution; `dot__`-prefixed dotfiles) and a
  source-checkout fallback so the CLI runs from a clone.

## [0.1.0] — 2026-06-08

Initial release.

### Added
- **Autonomous SDLC pipeline** — 24 specialized agents (`orchestrator`, spec/dev-doc writer,
  UI designer, senior developers, technical architect, EM reviewer, merge reviewer, developer,
  code reviewer, unit/e2e/integration testers, senior tester, auditor, devil's advocate,
  security reviewer + 4 sub-scanners, devops & observability engineers, PR raiser).
- **13 stack-agnostic rules** — workflow, quality gates, RARV self-check, working memory,
  agent memory, documentation, design patterns, code organization, linting/formatting, testing,
  frontend best practices, responsive/accessibility, and devops/observability.
- **42 on-demand skills** spanning planning, implementation, testing, review, security, and ops.
- **Two install channels from one source of truth**:
  - Claude Code **plugin** (`.claude-plugin/plugin.json` + `marketplace.json`, root-level
    component auto-discovery, portable hooks via `${CLAUDE_PLUGIN_ROOT}`).
  - **pip package** `claude-kit` (CLI `claude-kit` / `ckit`) that scaffolds the payload into any
    project's `.claude/` and root `CLAUDE.md`.
- **Slash commands** `/claude-kit:init`, `/claude-kit:sdlc`, `/claude-kit:status`.
- **Working memory** (`CONTINUITY.md`) and a **self-improving learnings loop** (`agent-memory/`)
  wired through SessionStart hooks.
- **Architecture documentation** with diagrams (`docs/architecture.md`).
