# Changelog

All notable changes to claude-kit are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses
[semantic versioning](https://semver.org/).

## [0.11.2] — 2026-06-15

A field review of **thirteen** more external collections — marketplaces, awesome-lists, subagent
packs, and hook/config repos — run through the same adversarial map→verify pass against the actual
kit files. Most are *distribution channels* (no copyable content) or *stack-specific* role packs that
would violate the agnostic core. Crucially, grounding the strongest candidates against the real hook
registry showed the kit **already** ships destructive-command blocking (`guard-rm-rf`,
`guard-push-main`), secret protection (`protect-secrets`, `guard-commit-secrets`), and skill
auto-routing (`skill-routing`) — refuting the headline ideas. Exactly **one** genuine gap survived.
Reviewed: [anthropics/claude-plugins-official](https://github.com/anthropics/claude-code) ·
claude-plugins-community · [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) ·
ccplugins/awesome-claude-code-plugins · rohitg00/awesome-claude-code-toolkit ·
[VoltAgent/awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents) ·
[0xfurai/claude-code-subagents](https://github.com/0xfurai/claude-code-subagents) ·
[disler/claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery) ·
yurukusa/claude-code-hooks (cc-safe-setup) · alirezarezvani/claude-skills ·
eddiemessiah/config-claude-code · ChrisWiles/claude-code-showcase.

### Added
- **`hooks/scripts/guard-destructive-git.sh`** + the `guard-destructive-git` hook (PreToolUse·Bash,
  `standard`→`enterprise`; absent in `lean`). A hard **block** (exit 2) for the git commands that
  irreversibly destroy *uncommitted* work — `git reset --hard`, `git clean -f`, and worktree-wide
  discards (`git checkout/restore .`) — each message pointing at the reversible alternative
  (`git stash`). This completes the `guard-rm-rf` / `guard-push-main` destructive-command family with
  the single most common irreversible agent mistake: nuking its own output. A *warn* would be theatre
  here (the command would still run and the work would be gone), so this is a guard, consistent with
  `guard-rm-rf`. Scope is deliberately git-only and conservative — no false positives on
  `git clean -n`, branch checkouts, or single-file restores; fail-open without `jq`. (+2 tests, 78.)

### Not adopted (deliberately, per the assessment)
- **Marketplaces** (anthropics official/community) — Apache-2.0 *distribution* manifests, not content;
  claude-kit already ships its own `.claude-plugin/marketplace.json`. Nothing to copy.
- **Awesome-lists** (hesreallyhim, ccplugins, rohitg00) — curated discovery indexes; no installable
  components of their own.
- **Subagent packs** (VoltAgent 154+, 0xfurai 100+; MIT) — overwhelmingly language/framework
  specialists (violate the stack-agnostic core) or roles the kit already has; `api-designer`→
  `technical-architect`/`api-and-interface-design`, `chaos-engineer`→`incident-responder`+`load-testing`,
  `penetration-tester`→`security-reviewer`/`owasp-reviewer`/`threat-model`, `product-manager`→ the org
  `pm-copilot` persona + `interview-me`/`idea-refine`. No genuine stack-agnostic SDLC role gap.
- **disler/claude-code-hooks-mastery** (no licence) — its destructive-command guard and skill-suggestion
  ideas are already covered (`guard-rm-rf`/`guard-push-main`, `skill-routing`); lifecycle hooks
  (SessionEnd/PreCompact continuity persistence) are covered by the continuity rule + `load-continuity`
  + the SessionStart:compact reload. The one residual — git work-loss blocking — became the adoption above.
- **yurukusa/cc-safe-setup** (MIT) — its **database-wipe** guard (`migrate reset`/`drop database`) was
  considered and **rejected as over-reach**: DB resets are legitimate in local dev and a hook can't tell
  dev from prod, so a block would break normal workflows and a warn would be theatre. DB risk stays
  governed by `risk-classification.md` (production-data/migrations → high/restricted) + `warn-sensitive-files`
  on migration edits.
- **alirezarezvani/claude-skills** — a codebase-onboarding skill duplicates `context-engineering` +
  `source-driven-development` (+ the org `repo-onboarding` skill).
- **eddiemessiah/config-claude-code, ChrisWiles/claude-code-showcase** (MIT) — personal config
  collections; the transferable ideas (tool-budget hygiene → `agent-guardrails`§3/`tool-design`/
  `context-engineering`; skill auto-suggestion → `skill-routing`; scheduled-maintenance CI → out of
  scope for a config-only kit, covered by `ci-cd-and-automation`/`devops-engineer`) are already covered.

## [0.11.1] — 2026-06-15

A field review of **seven** external projects, each run through the same adversarial map→verify pass
(read the source *and* the actual kit files; adopt only genuine, non-duplicative, config-only,
stack-agnostic, IP-safe gaps). The result is deliberately tiny: across all seven, exactly **one** real
gap survived — everything else is already covered, runtime-only, stack-specific, out of SDLC scope, or
IP-unsafe to copy. Reviewed: [obra/superpowers](https://github.com/obra/superpowers),
[wshobson/agents](https://github.com/wshobson/agents),
[anthropics/skills](https://github.com/anthropics/skills),
[karpathy/autoresearch](https://github.com/karpathy/autoresearch),
[browser-use](https://github.com/browser-use/browser-use),
[x1xhlol/system-prompts-and-models-of-ai-tools](https://github.com/x1xhlol/system-prompts-and-models-of-ai-tools),
and [langgenius/dify](https://github.com/langgenius/dify).

### Changed
- **`rules/testing.md`** — the "Async/Event-Loop Systems" guidance gains a **condition-based waiting**
  rule (distilled from superpowers' `condition-based-waiting`, MIT, re-expressed in original,
  stack-agnostic words): never wait on a fixed delay/sleep, poll for the observable condition instead
  (framework waiter or a small `wait_for(condition, timeout)`), and avoid the three flakiness traps
  (no timeout, interval too tight, stale reads). The section previously only said "mock I/O, use
  async/await" — it never addressed timing-dependent test flakiness.

### Not adopted (deliberately, per the assessment)
- **superpowers** — 14 skills, ~all duplicate existing kit skills (TDD, `systematic-debugging`→
  `debugging-and-error-recovery`, `brainstorming`→`idea-refine`/`doubt-driven-development`/`interview-me`,
  `writing-plans`→`planning-and-task-breakdown`, `executing-plans`→`execute`, `requesting`/`receiving-code-review`→
  `code-review-and-quality`, `using-git-worktrees`/`finishing-a-development-branch`→`git-workflow-and-versioning`/
  `shipping-and-launch`/`pr-raiser`, `verification-before-completion`→`rarv-cycle`+`mandatory-workflow`,
  `dispatching-parallel-agents`→`orchestrator`, `writing-skills`→`using-agent-skills`). Its
  `testing-anti-patterns` was refuted as a near-duplicate of the TDD skill's existing anti-pattern table.
- **wshobson/agents** — almost entirely language/framework specialists (violate the stack-agnostic core)
  or roles the kit already has (`code-reviewer`, `security-auditor`, `incident-responder`,
  `observability-engineer`, `performance-engineer`, `debugger`, `docs-architect`, `architect-reviewer`,
  database/devops roles), plus out-of-SDLC-scope domains (SEO, business, data-science). No general gap.
- **anthropics/skills** — document skills are source-available (not open) and out of scope; the example
  skills are out of scope (art/design/comms) or duplicative (`skill-creator`→`using-agent-skills`,
  `frontend-design`→`frontend-ui-engineering`). The `SKILL.md` `name`+`description` convention is already followed.
- **karpathy/autoresearch** — the closed-loop / single-metric / fixed-budget principles are covered by
  `evals` + `goal-setting-and-monitoring`; the ML-training loop itself is stack-specific. "Iterate the
  instructions, not the code" is what the kit already *is* (config-only).
- **browser-use** — a runtime library; browser automation is already covered by the opt-in `playwright`
  MCP entry + `browser-testing-with-devtools`/`playwright-verification`. Its "treat DOM/console/network
  as untrusted" guidance is already a verbatim "Security Boundaries" section in `browser-testing-with-devtools`.
- **x1xhlol/system-prompts** — GPL-3.0 archive of prompts extracted from proprietary tools (double IP
  hazard: copyleft + unresolved vendor rights). Its generic principles (plan-first, tool discipline,
  minimal diffs, verification, concise comms, refusal/secret-safety) are already in `reasoning-techniques`,
  `tool-design`, `mandatory-workflow`, `agent-guardrails`, `human-in-the-loop`, and `code-review-and-quality`.
  Nothing was copied.
- **langgenius/dify** — a runtime platform (Apache-2.0 *with additional conditions*); its principles
  (ReAct/function-calling agents, inspectable workflow steps, RAG stages, prompt-management feedback)
  are covered by `reasoning-techniques`, `tool-design`, `context-engineering`, `evals`, and `devops-observability`.

## [0.11.0] — 2026-06-15

Distils a field review of [repowise](https://github.com/repowise-dev/repowise) (a runtime
codebase-intelligence engine: dependency graph, git analytics, LLM wiki, code-health biomarkers,
change-risk, dead code). An adversarial map→verify pass over six candidates found that repowise is
overwhelmingly a **runtime product** whose config-equivalents claude-kit already ships — so the
honest, reuse-first result is small: one genuine kit-owned methodology gap and one sanctioned,
opt-in external-tool reference. No application code, no Docker, nothing bundled.

### Added
- **`catalog/mcp.yaml`** gains an **opt-in** `repowise` MCP server (codebase intelligence: hotspots,
  change-risk, co-change coupling, dead code). It is **only** written into `.mcp.json` when explicitly
  selected at init — the kit *references* repowise, never bundles it. The label flags that it is
  **AGPL-3.0** and requires installing it separately (`pip install repowise`) and indexing the repo
  once (`repowise init`); the repo path is supplied via the `${REPOWISE_PROJECT_ROOT}` env placeholder
  (same pattern as postgres's `${DATABASE_URL}`), so this is pure catalog data with no resolver change.

### Changed
- **`skills/code-review-and-quality`** gains a **"Where to Focus: Change Hotspots & Coupling"** section:
  a tool-agnostic, `git log`-only technique for spending review attention where defects cluster —
  churn × complexity hotspots, co-change coupling (hidden dependencies), and single-owner/bus-factor
  files. It notes that a codebase-intelligence MCP (e.g. the optional repowise server) provides the
  same signals precomputed via `get_risk`/`get_health`, but always as **advisory input, never a
  blocking gate**. A matching checklist item was added.

### Not done (deliberately, per the assessment)
- repowise's engine itself — dependency graph, dashboard (`repowise serve`), deterministic PR bot,
  LLM wiki/RAG, the 25 code-health biomarkers — is runtime and **cannot** be config. Its
  config-equivalents already exist and were **not** duplicated: dead-code hygiene
  (`over-engineering-review` / `code-simplification` / `code-review-and-quality` / `mandatory-workflow`),
  noisy-output compression a.k.a. "distill" (`tool-design` rule + `context-engineering` skill),
  read-an-overview-first (`context-engineering` / `source-driven-development`), ADRs
  (`documentation-and-adrs`), commit provenance (`git-workflow-and-versioning`), and auto-generated
  project instructions (`templates/CLAUDE.md`). No new rule/agent/skill/gate (the hotspot technique is
  advisory, so it enriches a profile-gated skill rather than becoming a mandatory rule).

## [0.10.0] — 2026-06-15

Adds **LLM / AI application-security** guidance distilled from a field review of
[protectai/llm-guard](https://github.com/protectai/llm-guard). An adversarial map→verify pass found a
real, single gap: claude-kit secured (a) the *agent itself* (`agent-guardrails`, OWASP **Agentic**
ASI01–10) and (b) *traditional* appsec of the product (`security-and-hardening` / `owasp-reviewer` =
OWASP Top 10 **2021** web), but **nothing** covered securing the **LLM features a user builds into
their product** (OWASP **LLM** Top 10 — prompt injection, insecure output handling, sensitive-info
disclosure, model DoS). Per your steer, the new layer is **opt-in, bypassable, and states the security
implications of bypassing** — and per golden rule #1 it reuses existing components rather than adding a
new rule/agent/gate (all of which the verify pass flagged as either over-engineering or, for a new
`rules/` file, a *mandatory*-framing conflict). No application code, no Docker; llm-guard is named only
as one reference implementation, never a dependency.

### Added
- **`hooks/scripts/warn-llm-io.sh`** + the `warn-llm-io` hook (`standard`+, after `warn-shared-modules`):
  an **advisory, non-blocking** PreToolUse(Edit|Write) hook. When an edited file looks like an LLM
  feature (provider SDKs / prompt construction / RAG), it surfaces the LLM guardrails and the explicit
  risks of skipping them (prompt-injection exfiltration, PII leaking to the provider,
  insecure-output-handling XSS/SSRF/RCE), and names the bypass: record a one-line risk acceptance. It
  always exits 0 (never blocks) and degrades to a no-op without `jq`.

### Changed
- **`skills/security-and-hardening`** gains an **"LLM / AI Feature Security (OWASP LLM Top 10) — opt-in"**
  section: the input→model→output guard architecture; input guardrails (prompt-injection screening,
  secrets scan, PII *anonymise/vault* pattern, token caps, topic limits, unicode canonicalisation);
  output guardrails (treat output as untrusted — no eval/render-raw/auto-run; PII/secret leak scan;
  malicious-URL/SSRF; structured-output validation); least-privilege model tools; an OWASP-LLM-Top-10
  map; a **risk-acceptance/bypass** protocol; and a **security-implications-of-bypassing** table. (The
  `security-reviewer` already reads this skill, so the security stage becomes LLM-aware for free.)
- **`skills/threat-model`** adds an LLM/AI trigger and a step-6 LLM branch (walk the LLM Top 10; point
  to the guardrails; record any bypass as a residual risk).
- **`agents/owasp-reviewer`** A08 now states that **model output is untrusted data** — the existing
  no-eval/exec/render-raw rule applies to it (insecure output handling stays a Critical), while the
  broader LLM guardrails are explicitly **advisory** and must not block the gate.

### Not done (deliberately, per the assessment)
- No new `rules/` file (a rule installs in every profile and reads as *mandatory* — conflicts with the
  opt-in requirement), no new `llm-security` agent, and no new blocking gate. The LLM Top 10 was **not**
  folded into the mandatory `owasp-reviewer`/Security Clear gate (that would make it mandatory and dilute
  a tightly-scoped 2021-web reviewer). LLM security stays a separate, advisory, bypassable path.

## [0.9.0] — 2026-06-15

Distils a field review of GitHub's [spec-kit](https://github.com/github/spec-kit) (Spec-Driven
Development). An adversarial map→verify pass cross-checked spec-kit's seven distinctive features
against claude-kit's existing spec-driven machinery; most were already covered (the `/constitution`
artifact by `CLAUDE.md` "Project-specific rules" + the org `ai-working-agreement`; `/clarify` by
`interview-me`; `/checklist` by `em-reviewer` + the spec-driven reframe + workflow §1b). Per golden
rule #1 (reuse, don't duplicate), those were **not** re-implemented. The genuine gaps were a
**built-but-unwired capability** and a **missing mechanism** — both addressed without new spec
machinery, no application code, and no Docker.

### Added
- **`skills/task-tracker-sync`** (`standard`+): a thin, **tracker-agnostic** skill that mirrors an
  existing task/story breakdown into the project's configured issue tracker (GitHub / Linear / Jira
  via whichever MCP is set up), one issue per task, dependencies carried across, idempotent
  (match-then-update, never blind-create). This implements spec-kit's `/taskstoissues` as the real
  mechanism behind what was previously only a permission — `story-planner` said tasks *may* be
  created, but nothing did it. It syncs a breakdown; it does not create one.

### Changed
- **Wired the orphaned `story-planner` agent into the pipeline as a coverage gate** — the headline
  reuse. `story-planner` already decomposes an approved spec into ordered stories and verifies that
  *every acceptance criterion maps to ≥1 story* (gaps and scope creep flagged), but it appeared in
  neither `rules/mandatory-workflow.md` nor `agents/orchestrator.md`. It is now **stage 1f — Story
  Breakdown & Coverage Gate**, between EM approval (1e) and the Developer (2a): implementation cannot
  start until acceptance-criterion coverage is complete. This is spec-kit's tasks→analyze→implement
  discipline, fulfilled with an existing component instead of a new one. Flow diagrams, the gating
  table, and the orchestrator pipeline/spawn-reference/state-tracking were updated to match.
- **`templates/artifacts/feature-spec.md`** now gives requirements stable ids (R1, R2 …) nesting
  their Given/When/Then acceptance criteria, and adds an explicit **Assumptions** section — aligning
  the artifact with the spec shape `mandatory-workflow.md` §1c already mandates and making the new
  coverage gate concrete (stories and tests trace back to R-ids).
- `agents/story-planner.md` and `skills/planning-and-task-breakdown` now point at `task-tracker-sync`
  for pushing a plan to a tracker.

## [0.8.0] — 2026-06-15

Adds a **minimalism / anti-over-engineering** layer distilled from a field review of the
[ponytail](https://github.com/DietrichGebert/ponytail) plugin. Most of ponytail's philosophy (YAGNI,
stdlib-first, surgical diffs) was already enforced by `templates/CLAUDE.md` "Simplicity First",
`skills/code-simplification`, and `rules/rarv-cycle`, so — per golden rule #1 (reuse, don't duplicate)
— only the genuinely-missing *mechanisms* were added. No application code, no Docker; new components
are wired through the catalog.

### Added
- **`skills/over-engineering-review`** (`standard`+): a complexity-**only**, report-**only** scan that
  returns a terse delete-list (`delete:/stdlib:/native:/yagni:/shrink:` tags, each naming the
  replacement) over a diff or a whole repo, ending with `net: -N lines possible` or `Lean already.
  Ship.`. Complements the multi-axis `code-review-and-quality` (it isolates the complexity axis) and
  stops short of the behavior-preserving refactor that `code-simplification` performs. Never flags the
  kit's required test or the safety carve-outs.
- **`skills/simplification-debt`** (`standard`+): harvests deliberately-deferred shortcuts
  (`TODO(TICKET)`, `FIXME`, and inline `shortcut: ceiling — upgrade` markers) into one ledger grouped
  by file, and flags any marker that names **no upgrade trigger** as a silent-rot risk. Report-only;
  persists to a file only when asked.
- **`load-autonomy` hook** (`SessionStart`, `standard`+): surfaces the repo's active autonomy level
  (read from the install snapshot) into context each session, so `rules/autonomy-levels.md` is visible
  and persistent rather than purely instructional. Degrades to a no-op without `jq`. Registered in the
  hook registry and the plugin `hooks/hooks.json`.

### Changed
- **`rules/evals.md`** gains section 6: run repeated trials and report the **median of N**, and
  **separate measurement metrics** (record-and-pass: LOC, cost, latency) **from gate metrics**
  (execute-and-fail: run the output, assert it) — with the ponytail benchmark cited as a worked example.
- **`rules/documentation.md`** now blesses an inline upgrade-path shortcut marker
  (`# shortcut: ceiling — upgrade path`) as an alternative to a ticketed `TODO`, and points at the
  `simplification-debt` skill that harvests them.
- **CI now publishes on merge to `main`, gated by a version check.** `publish.yml` also triggers on
  every push to `main` (in addition to version tags, releases, and manual dispatch). A `version-check`
  job compares `pyproject.toml`'s version against PyPI and only builds/publishes when the version is
  new; an unchanged version is skipped cleanly (PyPI versions are immutable). The publisher also passes
  `skip-existing: true` as a race guard. Net effect: bump the version in a PR, merge it, and the
  release ships automatically — no manual tag required.

## [0.7.1] — 2026-06-09

A parity fix for the no-pip fallback scaffolder so the plugin's `/claude-kit:init` command works
end-to-end when the Python CLI is not installed. No change to the scaffolded configuration.

### Fixed
- **`scripts/init.sh` now accepts `--defaults`.** The `/claude-kit:init` command advertises
  `[target-dir] [--defaults] [--force]` and passes the arguments straight through to the bundled
  shell fallback when neither `claude-kit` nor `ckit` is on `PATH` — but the fallback rejected
  `--defaults` with `unknown flag` (exit 2), breaking `/claude-kit:init --defaults` for plugin-only
  users. The flag is now accepted as a no-op for parity with `claude-kit init --defaults` (the shell
  scaffolder is already non-interactive). The pip-CLI path was never affected.

## [0.7.0] — 2026-06-09

Adopts durable AI-engineering practices mined from a curated knowledge base of industry articles
(Anthropic & Cursor engineering blogs, agent-harness write-ups, a security post-mortem, and
context-engineering essays) into the stack-agnostic core. Only **genuine gaps** were filled; existing
coverage was left intact to preserve description-based agent selection (golden rule #1). Still
config-only, stack-agnostic, no app code, no Docker; `resolve()` is unchanged — the two new rules are
always-on core (not catalog-gated).

### Added
- **`rules/evals.md`** — eval-driven development for AI/agent features: build a graded set before
  iterating, **grade outcomes not paths**, calibrate LLM-as-judge against human labels, report
  **pass@k vs pass^k**, keep regression + capability suites, re-eval before a model swap.
  *(Source: Anthropic "Demystifying evals for AI agents"; Cursor "Bench".)*
- **`rules/tool-design.md`** — designing tools/MCP for an agent consumer: composable CLI/code over
  always-loaded servers, progressive disclosure, single-line grep-friendly errors, print-sparsely /
  log-to-file, structured output for machine consumption, least-privilege + idempotency.
  *(Source: "What if you don't need MCP at all?"; "Building a C compiler with parallel Claudes"; "The
  Anatomy of an Agent Harness".)*
- The core rule set is now **23 files** (was 21); both new rules ship in every profile.

### Changed
- **`rules/agent-guardrails.md`** — added a **secure-defaults baseline** (localhost binding, no
  plaintext credentials, sandboxed execution, dependency/marketplace distrust) + an OWASP Top-10 for
  Agentic Apps (ASI01–ASI10) reference. *(Source: "From Clawdbot to OpenClaw".)*
- **`rules/agent-memory.md`** — **record the *why***, not just the *what* (decision traces: decision,
  reasoning, rejected alternatives, refs). *(Source: "Context Graphs".)*
- **`skills/_references/orchestration-patterns.md`** — the **three failure modes** the patterns counter
  (agentic laziness, self-preferential bias, goal drift) + a **programmatic fan-out** layer
  (fan-out-and-synthesize, generate-and-filter, tournament, loop-until-done).
  *(Source: "A harness for every task: dynamic workflows in Claude Code".)*
- **`skills/context-engineering/SKILL.md`** — a **context-degradation taxonomy** (poisoning,
  distraction, clash, lost-in-the-middle) + progressive disclosure / compaction / tool-output offloading.
- **`docs/agentic-patterns.md`** — coverage map updated; new "Digest-sourced additions" section records
  provenance for all of the above.
- Version bumped to **0.7.0**; `tests/test_scaffold.py` now asserts `evals.md` + `tool-design.md` ship
  in every profile.
- **PyPI distribution name is `claude-code-kit`.** The name `claude-kit` is blocked on PyPI by its
  typosquat guard (too similar to the existing `claudekit`), so the package publishes as
  `claude-code-kit` (`pip install claude-code-kit`). The CLI commands (`claude-kit` / `ckit` /
  `claude-sdlc`), the import package (`claude_kit`), the GitHub repo, and the Claude Code plugin name
  all remain `claude-kit` — only the PyPI project name changed.

### Fixed
Surfaced by a full install-readiness audit of both distribution paths (plugin + pip):
- **`git push` guard no longer over-blocks.** The PreToolUse guard matched the bare substrings
  `main`/`master` anywhere after `git push`, blocking legitimate branches (`maintenance`,
  `mainframe-fix`, `remaster-ui`, `domain-model`). It now anchors to the *target* ref token. Fixed in
  all three copies — `hooks/hooks.json`, `templates/settings.json`, and `src/claude_kit/hooks.py`.
- **Agent frontmatter uses the correct key.** Renamed the invalid `mode:` field to **`permissionMode:`**
  across all 26 agents (core + DB overlays); Claude Code silently ignores `mode:`, so the read-only
  `plan` / `acceptEdits` intent was dead config in scaffolded projects.
- **pip-CLI installs `skills/_references/`.** `claude-kit init` now copies the shared deep-dive
  references, so the "See Also" links in scaffolded `SKILL.md` files resolve (previously only the
  plugin / `init.sh` path shipped them); the `validate` skill count now requires a `SKILL.md` so the
  shared dir is not counted as a skill.
- **`rules/quality-gates.md`** scopes the Devil's Advocate pass to the profiles that install the agent
  (standard, enterprise); the **lean** fast track no longer carries a dangling `devils-advocate` ref.
- **Doc rule counts corrected** to **23** in `README.md` and `docs/architecture.md` (were 21); the
  README rule list now includes `evals` and `tool-design`.

## [0.6.0] — 2026-06-09

Adds an **Organization Vibe-Coding Capability Layer** so the kit serves whole organizations —
engineers, PMs, designers, QA, DevOps, security, data, support, and founders — driving work in natural
language *safely and consistently*. The design follows "reuse, don't duplicate": capability **packs**
map roles to the components the kit already ships, and only genuinely-new content (the vibe-coding /
non-engineer layer, safety & compliance policies, risk classification, and a few deterministic hooks)
is created. A new **org** install dimension joins `profile` (subset) and `stack` (overlay); it is
**scope-gated** and activates only when `scope == organization`, so existing team/individual installs
are unchanged except for two new always-on core rules. Still config-only, stack-agnostic, no app code,
no Docker; `resolve()` stays branch-free (the org layer is pure `catalog/org.yaml` data +
`templates/org/` content).

### Added
- **`catalog/org.yaml`** — the org data contract: `scopes` (individual/team/**organization**, default
  team), `teams`, an **autonomy** model (advisory → assisted → autonomous-local → autonomous-pr →
  enterprise-controlled, default **assisted**) where each level lists the hooks it enables, a
  **strictness** axis (light/standard/regulated) with extra gates, and the **7 packs** mapping roles to
  components. Read the same branch-free way as `profiles.yaml` / `mcp.yaml`.
- **`templates/org/`** — the org overlay payload, installed only in organization scope: 5 non-engineer
  **skills** (`feature-from-idea`, `prototype-to-production`, `customer-issue-to-fix`,
  `prompt-to-safe-task`, `repo-onboarding`), 5 persona **agents** (`pm-copilot`,
  `founder-prototype-agent`, `support-ticket-engineer`, `data-workflow-agent`, `internal-tools-builder`),
  10 policy/vibe **rules** (`ai-working-agreement`, `prompt-to-task-conversion`,
  `non-engineer-safe-coding`, `prototype-boundaries`, `ambiguity-resolution`, `secrets-policy`,
  `production-data-policy`, `pii-policy`, `branch-and-pr-policy`, `compliance-policy`), and **7 pack
  manifests + READMEs** (`engineering-core`, `product-to-code`, `quality-and-review`,
  `security-and-compliance`, `devops-and-release`, `onboarding-and-docs`, `non-engineer-builder`).
  Skills/agents/rules install into the auto-discovered `.claude/{skills,agents,rules}`; packs +
  governance index land under `.claude/org-packs/`.
- **Two core rules** (`rules/`, ship in every profile/scope): `autonomy-levels.md` (the 5 levels and
  what each permits, default assisted) and `risk-classification.md` (low/medium/high/restricted tiers
  + the high-risk protocol: plan · approval · security review · test review · rollback notes ·
  residual-risk summary). Rule set is now **21 files** (was 19).
- **Two core skills** (`skills/`, activated in `standard`+): `threat-model` and `accessibility-review`
  — two general gaps with no prior dedicated skill. Core skills are now **46** (was 44).
- **`agents/risk-classifier.md`** — a read-only `plan`-mode agent that classifies work into the risk
  tiers; activated in the `enterprise` profile and in org mode. SDLC agents are now **28** (was 27).
- **Six deterministic hooks** (`hooks/scripts/` + `HOOK_REGISTRY`), enabled by autonomy level via
  `org.yaml` (kept out of the default profiles): `warn-sensitive-files`, `warn-large-edits`,
  `warn-missing-tests`, `validate-frontmatter`, `validate-settings`, and `audit-log` (appends
  `ts·tool·target` to `.claude/state/audit.log` — **local only**, never external, never file bodies).
  All degrade to no-ops without `jq`.
- **`docs/org-capabilities.md`** — the requested→existing **coverage map** (the "reuse, not duplicate"
  evidence): every requested agent/skill/rule mapped to an existing component or a new file.

### Changed
- **CLI / resolver / installer** (`src/claude_kit/`): `Selection` gains org fields
  (`scope`/`teams`/`autonomy`/`review_strictness`/`org_packs`, all defaulted → back-compatible);
  `interactive()` asks scope first and (in organization scope) teams/autonomy/strictness/packs;
  `from_config()` parses the same keys; `catalog.resolve()` builds an `OrgPlan`, unioning pack
  components + autonomy hooks + strictness gates into the plan; `scaffold._install_org()` writes the
  overlay only when `plan.org` is set.
- **`catalog/profiles.yaml`** — `standard` gains `threat-model` + `accessibility-review`; `enterprise`
  gains `risk-classifier`.
- **`rules/model-tiers.md`** — records `risk-classifier` (sonnet) and the org persona agents.
- **CLI stubs** — `claude-sdlc package-org-pack` / `install-org-pack` print a "planned" message
  (mirroring the existing `research import-sources` stub).
- The generated per-project README gains an **"Organization-wide vibe-coding capabilities"** section
  (capability matrix, autonomy model, risk classification, distribution model, governance, metrics, and
  five worked examples across PM / engineer / QA / support / founder).
- Docs now reference **28** SDLC agents, **46** skills, and a **21-file** rule set — `README.md`,
  `CLAUDE.md`, `docs/architecture.md`, `docs/agents.md`.

### Notes
- ~70% of the requested org components already existed and were **mapped**, not recreated (e.g.
  `code-reviewer`→`sdlc-code-reviewer`, `security-engineer`→`security-reviewer`,
  `system-architect`→`technical-architect`, the requested stack rules → existing `templates/stacks/`
  overlays). See `docs/org-capabilities.md` for the full map.

## [0.5.0] — 2026-06-09

Imports a curated set of components that were proven in a downstream project and generalized back
into the kit: two SDLC skills, an incident-response agent, a model-tier reference rule, a commit-time
secret guard, and PostgreSQL performance overlays. Everything was neutralized of app/stack specifics
before landing — the agnostic core stays stack-free; PostgreSQL detail lives only in the db overlay.
No application code, no Docker.

### Added
- **Two SDLC skills** (`skills/`, activated in `standard` and up):
  - `incident-postmortem` — blameless postmortem: timeline, 5-whys, contributing factors, and tracked
    action items. Reads the project's structured logs / error-tracking and monitoring tooling.
  - `load-testing` — tool-agnostic performance/throughput testing (k6, Locust, etc. as examples).
    Distinct from the frontend `performance-optimization` skill.
- **`agents/incident-responder.md`** — a `plan`-mode stage-lead that triages live incidents (health/
  readiness checks, recent service logs, common suspects) and hands off to the `incident-postmortem`
  skill. Activated in the `enterprise` profile.
- **`rules/model-tiers.md`** — a core reference mapping each agent to a model tier
  (critical → opus, default → sonnet, fast → haiku), so model selection is explicit and auditable.
  Cross-linked from `reasoning-techniques.md`. Rule set is now **19 files** (was 18).
- **`hooks/scripts/guard-secrets.sh`** + the `guard-commit-secrets` hook (`PreToolUse`/`Bash`,
  `standard`+) — blocks `git commit` when staged files or staged content look like secrets. Complements
  the existing read-time `protect-secrets` guard.
- **PostgreSQL overlays** (`templates/stacks/db/postgres/`, installed only when PostgreSQL is chosen):
  - `rules/database-performance.md` — N+1 avoidance, composite/tenant indexes, keyset pagination,
    async connection-pool tuning.
  - `agents/db-performance-reviewer.md` — a `plan`-mode reviewer for query/index/pooling regressions.

### Changed
- `catalog/profiles.yaml` — `standard` gains the two skills + the commit-secret hook; `enterprise`
  gains `incident-responder`.
- `catalog/stacks.yaml` — the PostgreSQL stack wires the new overlay rule + overlay agent.
- Docs now reference **27** SDLC agents (was 26) and a **19-file** rule set (was 18) — `README.md`,
  `CLAUDE.md`, `docs/architecture.md`, `docs/agents.md`, `docs/agentic-patterns.md`.

### Notes
- Four other candidate skills from the source project were evaluated and **not** imported — already
  covered by existing kit skills (e.g. security hardening, debugging/error recovery, planning).

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
