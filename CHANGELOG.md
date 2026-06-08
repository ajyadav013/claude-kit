# Changelog

All notable changes to claude-kit are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses
[semantic versioning](https://semver.org/).

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
