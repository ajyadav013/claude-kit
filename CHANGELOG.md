# Changelog

All notable changes to claude-kit are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses
[semantic versioning](https://semver.org/).

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
