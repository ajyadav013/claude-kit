<div align="center">

# claude-kit

**Turn Claude Code into a disciplined engineering team: one command — `/sdlc <task>` — runs your
request through spec → review → code → test → security → PR, with a quality gate between every
phase.**

The differentiator is trust: **no gate passes without real, cited command output**, so a green
result means the checks actually ran. It installs as **configuration only** — no runtime, no
application code, no Docker.

<!-- DEMO PLACEHOLDER — a 60–90s terminal capture of a gated `/sdlc` run belongs here once recorded.
     Shot list, timing, and which real assets to show: docs/launch/demo-script.md.
     The recording replays the genuine run already in examples/real-run/ (the devils-advocate catching a
     Medium bug a unanimous review missed, and the gate refusing to advance until it was fixed).
     Until the GIF exists, that folder IS the evidence — linked from "How it works" and "The pipeline" below. -->

[![PyPI](https://img.shields.io/pypi/v/claude-code-kit.svg)](https://pypi.org/project/claude-code-kit/)
[![Python](https://img.shields.io/pypi/pyversions/claude-code-kit.svg)](https://pypi.org/project/claude-code-kit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Built for Claude Code](https://img.shields.io/badge/built%20for-Claude%20Code-d97757.svg)](https://www.claude.com/product/claude-code)
[![CI](https://github.com/ajyadav013/claude-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/ajyadav013/claude-kit/actions/workflows/ci.yml)
[![Changelog](https://img.shields.io/badge/changelog-md-blue.svg)](CHANGELOG.md)

⚡ [Quick start](#quick-start) · 🧭 [How it works](#how-it-works) · 🔁 [The pipeline](#the-pipeline) · ⚖️ [Compare](#how-claude-kit-compares) · 🔒 [Security](#security--trust-model) · 📚 [Docs](#docs--deeper-reference)

</div>

---

## What is this?

Claude Code is brilliant at single tasks — but a real change is never just one task. It's a spec, a
plan, code, review, tests, a security pass, a PR. **claude-kit turns that whole lifecycle into a
pipeline of focused agents and installs it into Claude Code as configuration.**

Your request flows through specialists — a spec writer, a developer, independent reviewers, testers,
security scanners, a PR raiser — coordinated by an **Orchestrator** that runs independent work in
parallel and **refuses to advance until each phase's quality gate passes**. Choose your stack, rigor,
and team scope at `init`; everything else adapts.

**Use claude-kit if** you drive real repository changes with Claude Code and want a repeatable
spec → review → test → security → PR workflow whose quality gates won't advance on an unproven verdict.

**Skip it if** you want a small prompt pack, don't want project config written into your repo, or need a
standalone runtime/daemon. claude-kit is **configuration for Claude Code**, not a separate runtime — and
its guard hooks are convenience guardrails (they need `jq` + a POSIX shell and no-op without them), **not
a hardened security boundary**. See [Known limitations](docs/KNOWN_LIMITATIONS.md).

---

## Quick start

The fastest path to a gated run — **no CLI install, no `init`, no restart:**

```text
/plugin marketplace add ajyadav013/claude-kit
/plugin install claude-kit
/claude-kit:sdlc Add a /health endpoint that returns the build version
```

That's the whole loop in three lines: the standard pipeline runs immediately — spec → review →
build → test, gate by gate — with every verdict backed by real output.

**Proof it works:** [`examples/real-run/`](examples/real-run/) is a genuine captured run where the
`devils-advocate` caught a Medium bug a unanimous review missed, and the gate refused to advance
until it was fixed.

When you want the pipeline tuned to *your* repo — your stack, commands, rigor profile, and the
safety hooks — run `init`:

<details open>
<summary><b>A) As a Claude Code plugin&nbsp; (recommended)</b></summary>

<br>

```text
/claude-kit:init        # Claude asks you the questions in chat, then runs the CLI non-interactively
# ↻ restart Claude Code so the project's agents, skills & hooks load
/sdlc Add a CSV export button to the reports page
```

> `/claude-kit:init` needs the Python CLI on PATH (`pipx install claude-code-kit`) — it resolves
> your stack/profile and records checksums for safe `upgrade`. Details: [docs/install.md](docs/install.md).

</details>

<details>
<summary><b>B) As a pip package&nbsp; (CI, onboarding, non-plugin workflows)</b></summary>

<br>

```bash
pip install claude-code-kit             # note: the pip name is claude-code-kit, not claude-kit

claude-kit init                 # interactive: prompts for stack, profile, MCP
claude-kit init --defaults      # non-interactive: React + Python/FastAPI + Postgres + standard
```

</details>

> **Prerequisites:** [Claude Code](https://www.claude.com/product/claude-code); Python ≥ 3.9 for the CLI;
> `jq` for the shell hooks (they no-op without it). **Windows** users: run inside WSL or Git Bash for
> the hooks. Every install question, the `init.yaml` format, what lands on disk, and plugin-update
> steps: **[docs/install.md](docs/install.md)**.

---

## What you get

| Area | What you get |
|------|--------------|
| 🔁 **Pipeline & quality gates** | Gate-enforced progression — a phase advances only with zero open Critical/High/Medium findings — plus a fast-track for small changes and an anti-sycophancy `devils-advocate` pass |
| 🤖 **Agent roster** | **28** tiered agents led by an Orchestrator that never writes code, plus per-database overlay agents and 6 org personas ([full roster](docs/agents.md)) |
| 📐 **Rules & skills** | **25** stack-agnostic core rules + **105** context-activated skills (57 core + 48 stack-collection), pulled into context on demand |
| 🧱 **Stacks & overlays** | A stack-agnostic core + **13** overlay rule files (React · FastAPI · Go · Postgres · Mongo) wired to your exact commands and path-scoped to load only when you touch matching files |
| 🛠️ **Hooks & guards** | **18** event hooks — deterministic safety guards and advisory warnings — that no-op gracefully without `jq` |
| 📦 **Distribution & lifecycle** | Plugin **and** pip from one source, **22** ready MCP fragments (version-pinned), edit-preserving `upgrade`, and a root `AGENTS.md` at init so non-Claude agents share the same standards |

Profiles (`lean` · `standard` · `enterprise`), team scopes, autonomy levels, and org capability
packs decide how much of this actually installs — see
[Profiles & what lands in your project](#profiles--what-lands-in-your-project).

---

## How it works

Four ideas do the heavy lifting:

1. **Evidence or it didn't happen.** Every gate verdict — PASS or FAIL — must cite the command that
   ran and its captured output. A verdict that's invented, assumed, or read off still-running work
   is an **auto-Critical finding** — the same severity as a hardcoded secret
   ([`quality-gates.md` §2.5](rules/quality-gates.md)).
2. **Quality gates with a shared severity model.** Every finding is classified
   Critical / High / Medium / Low / Cosmetic. A gate passes **only** with zero Critical/High/Medium
   open. No silent advancement.
3. **RARV self-check.** Every agent runs **R**eason → **A**ct → **R**eflect → **V**erify and must show
   a *green Verify* (real commands run, not imagined) before handing off.
4. **Blind review + Devil's Advocate.** Parallel reviewers judge independently; a *unanimous* PASS
   triggers an adversarial `devils-advocate` pass before the gate may close — an explicit guard
   against agents rubber-stamping each other.

See [`docs/architecture.md`](docs/architecture.md) for the full diagrams, including how one source
of truth ships as both a plugin and a pip package.

---

## The pipeline

`/sdlc` reads the profile you chose and runs **only that profile's gates**:

```mermaid
flowchart TD
    REQ(["/sdlc request"]) --> CLS{"Classify"}
    CLS -->|"feature"| SPEC["Spec & Dev Docs"]
    SPEC --> EM{{"Gate: EM approved"}}
    EM -->|"pass"| STORY["Story breakdown + coverage gate<br/>story-planner"]
    STORY --> LANES["Parallel lanes:<br/>Senior Dev → Architect → Developer → Code Review"]
    LANES --> MR{{"Gate: Merge Reviewer"}}
    MR --> TEST["Unit · E2E · Integration + Senior verification"]
    TEST --> TCG{{"Gate: Test coverage<br/>+ Devil's Advocate"}}
    TCG --> SEC{{"Gate: Security Clear"}}
    SEC --> OPS{{"Gates: Pipeline Green ·<br/>Observability Ready · Acceptance"}}
    OPS --> PR["PR Raiser"] --> HUMAN(["Human review + deploy"])
    CLS -->|"fast-track (<5 files)"| FT["Developer → Review → Test → PR"] --> HUMAN
```

| Profile | Gates that run |
|---|---|
| **lean** | code-review · build-green |
| **standard** | spec-complete · em-approved · code-review · build-green · test-coverage · security-clear · contract-clear\* |
| **enterprise** | standard + pipeline-green · observability-ready · acceptance |

\* `contract-clear` (API breaking-change diff) self-skips when the stack exposes no API surface.
A **fast-track** mode collapses small changes (< 5 files) to Developer → Code Reviewer → Tester → PR;
organization scope at `regulated` strictness adds `accessibility-clear` (WCAG-AA on changed UI).

See the real captured run in [`examples/real-run/`](examples/real-run/) — a feature driven through
every gate on a Go project, with the verbatim state file, agent verdicts, diff, and an asciicast —
or the [synthetic walkthrough](examples/react-fastapi-postgres-feature/) of the default stack. To
capture your own publishable run: [`docs/capture-a-real-run.md`](docs/capture-a-real-run.md).

---

## Profiles & what lands in your project

The profile you pick decides how much lands in `.claude/`. Measured on a React + FastAPI +
PostgreSQL project, individual scope:

| Profile | Agents | Skills | Rules |
|---------|-------:|-------:|------:|
| `lean` | 8 | 15 | 36 |
| `standard` (default) | 26 | 43 | 36 |
| `enterprise` | 31 | 105 | 36 |

- **Rules are profile-independent** — every profile installs the same 25 core rules + the selected
  stack's overlays (11 for this stack = 36); rigor changes the *agents and gates*, not the rule set.
- **Installs are stack-true** — every lane offers `none`, and a lane you don't have installs
  nothing: a backend-only project gets no React rules, frontend skills, or npm commands.
- **`enterprise` installs the whole skill collection** — including stacks you didn't select. That's
  disk footprint, not always-resident context, but prefer `standard` for a tighter install. See
  [`docs/skill-audit.md`](docs/skill-audit.md).

Organization scope adds teams, 5 autonomy levels, review strictness, and capability packs — see
[`docs/org-capabilities.md`](docs/org-capabilities.md).

---

## How claude-kit compares

The closest alternative is just **using Claude Code's own subagents** — and that's the comparison
that matters most: **native gives you the agents; claude-kit gives you the governance.**

| Compared to… | What it is | What claude-kit adds |
|---|---|---|
| **Native Claude Code subagents / Agent Teams** | Spawn parallel agents on demand; you define workflow and verification yourself each time | A fixed, sequenced pipeline with owned gates, an evidence requirement for every verdict, the `devils-advocate` anti-rubber-stamp pass, and structured resume from the pipeline state file |
| **[wshobson/agents](https://github.com/wshobson/agents)** & similar collections | Large libraries of individual subagent prompts you pick from | A smaller, opinionated set wired into a sequenced pipeline — agents are stages that hand off and block on each other, not a menu |
| **[GitHub spec-kit](https://github.com/github/spec-kit)** | Spec-driven development as a platform: constitution → spec → tasks → analyze, plus label-driven CI stages | The same coverage-gate idea absorbed into a broader in-session lifecycle — review, security, build, test, release, and observability gates with enforced severity blocking. Complementary: their CI stages, this kit's gate depth ([details](docs/autonomous-operation.md)) |
| **claude-flow / multi-agent runtimes** | Runtime orchestrators that *execute* swarms of agents | Portable configuration, not a running process — no daemon, no lock-in, no app code |
| **dotfiles / `CLAUDE.md` starters** | A single rules file or settings snippet | A catalog-driven generator: resolves your stack/profile/scope into the right subset of 25 rules, 28 agents, 105 skills, gates, and hooks — kept upgradeable with your edits preserved |

**Choose claude-kit when** you want a consistent, gate-enforced autonomous-SDLC setup that's the
same across every repo and stack, installs in seconds, and ships nothing you have to run. It is
**not** a runtime or a code library — it's the configuration that makes Claude Code's agents behave
like a disciplined team.

---

## Use beyond Claude Code (export)

`init` already emits a repo-root **`AGENTS.md`** so teammates on Cursor, VS Code, or Copilot get the
kit's standards from day one. `claude-kit export` projects the full config into their native formats:

```bash
claude-kit export . -t cursor -t agents -t copilot
```

**Fidelity is honest:** rules, the project charter, and MCP servers port cleanly; the *enforced*
gates and reviewer subagents are Claude-Code-only and travel as a single-agent checklist instead —
every exported document says so. Full fidelity matrix: [`docs/cursor-export.md`](docs/cursor-export.md).

---

## Influences & reuse-first

claude-kit evolves by reviewing excellent open-source projects and industry material, then adopting
**only the genuinely-new ideas** — each review fetches the real source, adversarially maps it against
the kit's existing files, and ships only the non-duplicative gaps (many reviews conclude with
"0 new agents/skills/rules" on purpose). The full adoption history — from Agentic Design Patterns
through the alibaba/microsoft/google/Meta/Netflix·aws·apple org reviews — lives in
[`docs/influences.md`](docs/influences.md), with per-release detail in the [CHANGELOG](CHANGELOG.md).

---

## Security & trust model

claude-kit installs **configuration only** — no application code, no Docker, nothing that runs as a
service. Three honest caveats before you rely on it:

- **The guard hooks are convenience, not a hardened boundary.** They raise the cost of a mistake but
  don't sandbox the agent; they need a POSIX shell + `jq` and silently no-op without them. Seatbelts,
  not walls.
- **Most quality gates are agent protocols, not mechanical enforcement.** Only the hook scripts are
  deterministic, host-enforced checks; a capable model can still be wrong or skip a step — keep a
  human in the loop for anything that matters. Relatedly: the agents' `permissionMode` confinement
  (read-only reviewers) binds only in **init-scaffolded** projects — plugin-loaded agents ignore
  it, so run the pipeline from a scaffolded project when that confinement matters.
- **MCP servers are third-party code.** Each fragment runs an external package — pinned to an exact
  version, never `@latest` — that claude-kit references but does not vendor or audit. Review a
  server's source and license before enabling it.

Releases are published to PyPI via OIDC **Trusted Publishing** with **PEP 740 build attestations**.
Report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md).

---

## Docs & deeper reference

| Doc | What's in it |
|---|---|
| [`docs/install.md`](docs/install.md) | Every install detail: prerequisites, Windows, plugin updates, all `init` questions, `init.yaml`, what lands on disk |
| [`docs/cli.md`](docs/cli.md) | Full CLI command reference, safe-upgrade mechanics, troubleshooting |
| [`docs/agents.md`](docs/agents.md) | How to drive the agents + the full 28-agent roster and per-run cost |
| [`docs/architecture.md`](docs/architecture.md) | Diagrams: distribution, catalog resolution, the state machine — and how to extend via the catalog |
| [`docs/influences.md`](docs/influences.md) | The reuse-first adoption history: what we learned, shipped, and deliberately skipped |
| [`docs/autonomous-operation.md`](docs/autonomous-operation.md) | Unattended runs: permission modes × autonomy levels, headless mode, the bounded loop script, CI-trigger design |
| [`docs/cursor-export.md`](docs/cursor-export.md) | Export fidelity matrix and `.mdc` mapping |
| [`docs/org-capabilities.md`](docs/org-capabilities.md) | Organization scope: packs, personas, autonomy, review strictness |
| [`docs/skill-audit.md`](docs/skill-audit.md) | Per-profile skill footprint and context economics |
| [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) | What the kit deliberately does not claim |
| [`examples/real-run/`](examples/real-run/) | The captured, gated real run (evidence, not marketing) |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contributor workflow; [`CLAUDE.md`](CLAUDE.md) covers developing the kit itself |

---

## Contributing

Issues and PRs welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md). To dogfood a local checkout:

```bash
# As a plugin:  /plugin marketplace add .   then   /plugin install claude-kit
# As the CLI:   pip install -e '.[dev]'   then   claude-kit init /tmp/demo --defaults   &&   pytest
```

## License

[MIT](LICENSE) © Arjunsingh Yadav
