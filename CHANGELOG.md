# Changelog

All notable changes to claude-kit are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses
[semantic versioning](https://semver.org/).

## [0.58.1] — 2026-07-07

**Pipeline agents can now actually persist what their prompts mandate.** An industry-review pass
(4 web researchers + 4 repo specialists, adversarially synthesized) found the kit's flagship
resumable-pipeline promise structurally broken: nine agents ran `permissionMode: plan` (read-only)
while their prompts *required* file writes — the orchestrator's `CONTINUITY.md` +
`.claude/state/pipeline-snapshot.json` updates, every security scanner's `docs/security/*` report,
the merge-reviewer's API change report, and the incident-responder's incident log. Plus the docs-truth sweep the same review surfaced.
0 new agents/skills/rules; catalog untouched.

### Added

- **The stack→collection-skill mapping, measured** — `docs/skill-audit.md` gains the classification
  the audit's own "evaluate `skills: stack-relevant`" item called for: all 48 collection skills
  classified against the lanes actually selectable today. Headline: **22 of 48 are
  infra/platform-orthogonal** (Kafka/Temporal/Redis/GCP/k8s/observability — choices `init`'s three
  stack questions never ask about) and 4 more are stack-generic, so a lane-based filter installs
  **46 of 48 for the default react+fastapi+postgres selection** (only the two planned-stack Node
  skills drop) — refuting the audit's "roughly a dozen-plus instead of 48" estimate. The only
  selection where filtering is material is go backend-only (26 of 48). The table ships as the
  reusable input for a future **infrastructure axis** at init, which is the real lever.
- **Collection-skill size sweep** (the deferred follow-up from the skills-hygiene pass; measured
  per-file first). All five oversized collection SKILL.md files turned out to already ship
  `references/` — the earlier "no references/ yet" note was an artifact of a truncated directory
  listing — and the fat in each was a `## Skeleton / example` section of complete worked files
  injected on every trigger. Three fixed: **`docker-compose` 606 → 253** (the four full compose
  files — base, dev, prod-test, profiles — moved verbatim to new `references/compose-skeletons.md`
  behind an annotated pointer); **`grafana-dashboards-and-alerts` 535 → 437** (the RED dashboard
  JSON + three-stage unified alert rule moved verbatim to new
  `references/red-dashboard-skeleton.md`); **`containerization-and-deployment` 534 → 262** (its
  five skeletons were verbatim *duplicates* of content already in its own references — grep-verified
  block-by-block before deletion — so the section became a per-skeleton pointer map with zero
  content loss). Two refused for consistency with the earlier `manual-test` (516) refusal:
  `langfuse-llm-tracing` (508) and `redis-caching-patterns` (505) sit 1–2% over the ~500-line
  guidance, under the same not-worth-the-cohesion-cost threshold.
- **Hooks-layer modernization review resolved with evidence** — the industry review's four
  gen_hooks claims (left unverified when the hooks-specialist research agent died mid-workflow)
  were each checked against the official hooks reference + the Claude Code changelog; **all four
  were refuted or refused** (see *Not adopted*), so the hook layer ships unchanged — deliberately.
  The verified facts are now recorded where they prevent re-litigation: a format-decisions comment
  above `HOOK_REGISTRY` (exact-match matcher semantics; the exec-form 2.1.139 floor; exit-code-2
  blocking is not deprecated), and `docs/autonomous-operation.md` §3 now documents `/goal` — Claude
  Code's *built-in* session-scoped prompt-based Stop gate — as the zero-config alternative to the
  bounded loop for single interactive sessions. All five registry events re-verified present in
  the current event list (no drift).
- **`docs/autonomous-operation.md` — autonomy grounded in the shipped CLI, not folklore** (every
  flag and mode verified against Claude Code 2.1.178 `--help` + the official permissions docs
  before writing). Headless `claude -p` documented with its three safety-relevant property changes
  (prompts become denials, the trust dialog is skipped, invalid settings are *silently ignored* —
  so validate before the run, not after); the `--bare` caveat spelled out concretely for a kit
  project (it skips hooks **and** CLAUDE.md auto-discovery, so SessionStart context, every guard
  hook, and the rules contract all vanish — including `load-autonomy.sh`, meaning a bare run
  doesn't know its own ceiling); a bounded headless-loop pattern built on the kit's real resume
  seam (`CONTINUITY.md` + `pipeline-snapshot.json` `last_gate_passed`) with three deliberate
  brakes (iteration cap, `--max-budget-usd`, stall detection → nonzero exit for a human); the
  five `autonomy-levels.md` levels mapped onto the six real permission modes (`acceptEdits` ·
  `auto` · `bypassPermissions` · `manual` · `dontAsk` · `plan`), with `bypassPermissions`
  explicitly mapped to **no** kit level (its own docs restrict it to isolated sandboxes) and
  `enterprise-controlled` pinned via managed-settings `disableBypassPermissionsMode`; and an
  anti-gaming table wiring five unattended-log warning signs to the shipped defenses
  (`quality-gates.md` §2.5 evidence requirement, `continuity.md` verify-before-trust,
  blind-review/Devil's-Advocate, `audit-log`). Correction to the review's claim recorded inline:
  the CLI has **no `--max-turns`** flag (2.1.178; that's an Agent SDK feature) — iteration caps
  belong in the loop script.
- **Skills hygiene: progressive disclosure for the heaviest core skill + honest triggers** (every
  review claim measured first). `security-and-hardening/SKILL.md` — at 718 lines the largest
  SKILL.md in the payload, injected wholesale on every trigger — is split along its decision seam:
  the boundaries / per-class rules / checklists / red-flags layer stays in SKILL.md (286 lines),
  and the code patterns and deep-dive practices move **verbatim** (license attributions included)
  to four on-demand `references/` files — OWASP per-class patterns + continuous least-privilege ·
  input-validation/uploads/archive-extraction/ReDoS · supply-chain triage/SBOM/reproducible-builds/
  missing-patch · LLM guardrail specifics — the same convention 20+ collection skills already
  follow. Everything external actors deep-link into the file (`warn-llm-io.sh` and
  `owasp-reviewer` → *LLM / AI Feature Security*, `dependency-scanner` → *Triaging Dependency
  Audit Results*, the scaffold test's three anchors) stays in SKILL.md under its original title.
  Trigger honesty: `containerization-and-deployment`'s description stops claiming its four
  siblings' territory (multi-stage builds → `dockerfile-backend`, compose local dev →
  `docker-compose`) and owns the overview role explicitly; `remember`'s dangling "injects the
  index below" now names what the hook actually injects (`.claude/agent-memory/MEMORY.md`).
- **Cost transparency** — `docs/agents.md` gains a "What a run costs" section measured from the
  shipped frontmatter (4 `opus` agents — `orchestrator`, `developer`, `devils-advocate`,
  `owasp-reviewer` — everything else `sonnet`, the Fast tier deliberately unassigned), with the
  practical levers: the profile is the biggest knob (lean runs only 2 of the 4 `opus` agents), and
  tier escalation stays investigation-gated. **Fan-out is now announced before it happens**: the
  orchestrator (Spawning parallel agents), the `sdlc` skill (step 3), and the wave-orchestration
  rule (Cost discipline) all require stating the planned lane/agent count and model tiers — in
  chat and CONTINUITY.md — before any parallel phase forks, so a human can veto the scale before
  tokens are spent.
- **Stack-true installs: `none` lanes + frontend skills ride the frontend stack** (every sub-claim
  verified first). `catalog/stacks.yaml` gains `none` entries for frontend, backend, and database —
  previously a pure-backend project was *forced* to select React and received 8 React overlay
  rules, frontend skills, and npm commands in its CLAUDE.md. A `none` entry ships no
  overlays/skills/commands/stack_dir, so the branch-free resolver makes it a true no-op lane; new
  `has_frontend`/`has_backend`/`has_database` context flags (derived from stack_dir presence — data,
  not stack names) let `CLAUDE.stack.md.tmpl` + `README.claude-sdlc.md.tmpl` render clean charters
  for any combination, including all-`none`. The six frontend-specific skills
  (`frontend-ui-engineering`, `component-design`, `ui-ux-design`, `unit-test` "frontend components
  and hooks", `api-integration` client-side data fetching — verified by reading each skill's
  content, and previously mis-filed under the *backend* stacks — and `manual-test` headed-browser
  QA) moved from the standard profile core to the React entry's `skills:` union: a backend-only
  standard install is six skills lighter, the default-stack standard count is unchanged (42), and
  lean's default-stack count goes 14 → 15 (README + skill-audit updated; skill-audit's stale
  35-rules column also fixed to 36). The `none` combinations automatically join the
  profile×stack×scope self-test matrix. The interactive frontend-language question is skipped for
  a lane with no languages. Deferred to a future pass: the `skills: stack-relevant` enterprise
  filter (needs a collection-skill→stack mapping measured, not assumed).
- **`init` now emits a root `AGENTS.md`** — the cross-tool agent-instructions convention behind the
  most-requested Claude Code integration (anthropics/claude-code#6235, 4.3k 👍, re-verified OPEN and
  still non-native before adoption: Claude Code reads `CLAUDE.md` only, so this file serves the
  *other* agents in the repo — Cursor, Copilot, Codex — with zero double-load risk). The scaffolder
  reuses the `export` projection verbatim (charter + single-agent SDLC checklist + rule index +
  fidelity note), never clobbers a pre-existing `AGENTS.md` (sidecar), and records the file as
  `user-editable` so `upgrade` preserves edits. **User-file writes are now idempotent** across
  `init` and `export`: a byte-identical existing file is reported as "already current" instead of
  spraying `.claude-kit` sidecars on every re-run — real differences still sidecar.
- **Path-scoped overlay rules** — 12 of the 13 stack overlay rule files now open with `paths:` YAML
  frontmatter (Claude Code's official scoped rule loading, verified against
  code.claude.com/docs/en/memory before adoption), so React/FastAPI/Go/Postgres guidance enters
  context only when Claude touches matching files instead of riding every session. Globs live in the
  overlay files themselves — the stack-agnostic core rules stay deliberately unscoped (always-on
  contract), and `mongodb-patterns.md` stays unscoped on purpose: a document store has no reliable
  file signal, and a glob that never matches would mean the rule *never* loads (the same judgment
  `export._DB_GLOBS` already encodes). The Cursor exporter now projects a rule's own `paths:` list
  verbatim into `.mdc` `globs` (comma-joined; list form chosen over brace expansion precisely so it
  ports) and strips the source block so no export carries a double frontmatter; the language/db
  table remains as fallback for frontmatter-less overlays. New `tests/test_rule_frontmatter.py`
  pins all four invariants (scoped overlays valid, Mongo exception, core rules clean, scaffold
  copies verbatim).
- **Rule-count drift guards in CI** — `scripts/check_docs_consistency.py` now anchors the overlay
  rule-file count, the README's default-stack worked example (25 core + 11 overlays = 36), and the
  rule counts quoted in `docs/architecture.md`, so the count drift fixed below cannot recur silently.

### Fixed

- **Orchestrator: gate set now conditions on the installed profile, ghosts removed, three
  installed-but-never-spawned agents wired in** (every claim verified against the files first):
  a **lean** install ships 5 agents (`orchestrator, developer, sdlc-code-reviewer, tester,
  pr-raiser`) yet the orchestrator's NEVER-skip rules mandated ui-designer / technical-architect /
  em-reviewer / merge-reviewer / senior-tester stages that don't exist there — every lean run had
  to either violate a NEVER rule or stall. New **Active Gate Set** section: derive the run's gate
  set from the installed roster + profile at Stage 0 (`SKIPPED (not in profile)` is noted, never
  silent, never PASS; everything active stays mandatory), matching the `sdlc` skill's existing
  profile table. Removed the ghost **Design Specialist** (D2) and the separate **Spec
  Writer/Dev Doc Writer** stages from the diagram, feedback loops, comms pattern, state examples,
  and rule 5 — the roster has only the combined `ui-designer` and `spec-doc-writer` (same ghost
  fixed in `em-reviewer.md`). Wired in the three standard+ agents the pipeline never spawned:
  `unit-tester` authors the 4c unit suites per lane, `e2e-tester` is a conditional 4th testing
  lane (never installs frameworks), and `acceptance-reviewer` is new **Stage 5.6** gating on the
  enterprise `acceptance` token — which `rules/quality-gates.md` line 116 already assumed runs.
  New **Gate ↔ Stage Map** table gives `pipeline-snapshot.json` its canonical
  `last_gate_passed` tokens (aligned with `catalog/profiles.yaml` + the `sdlc` skill).
- **Agent executability bundle** (each defect verified against the file before fixing):
  `sdlc-code-reviewer` gains `Bash` — its own protocol names `git diff --name-only` "the checklist
  of record" but its tool list couldn't run git. `auditor` drops its `tools:` allowlist (it excluded
  the very Chrome-DevTools MCP tools the whole workflow drives) and moves `haiku` → `sonnet`
  (multi-step browser-MCP orchestration is not "mechanical reporting"); `model-tiers.md` updated to
  match, read-only now stated as explicit discipline. `developer`'s prerequisite health checks are
  now conditional and stack-neutral — the old version hardcoded `localhost:8000/3000/5173` and
  demanded a healthy stack "before writing any code", deadlocking fresh checkouts on pure code+test
  tasks. `senior-backend-dev` / `senior-frontend-dev` gain the **Spec Review Mode** the
  orchestrator's stages 3a-BE/3a-FE always expected of them (explicit `APPROVED`/`REVISE` verdict,
  max-3-iterations contract); `senior-backend-dev`'s three dangling skill references
  (`api-endpoint`, `database-migration`, `backend-unit-test` — none exist) now point at real
  content. `e2e-tester` no longer installs packages unprompted — missing frameworks are reported
  and routed through the developer lane per `dependency-verification` + the manifest-approval rule.
- **`/claude-kit:init` now actually works from Claude Code** — the plugin command told Claude to run
  the CLI's *interactive* flow, but the Bash tool has no TTY: with no path argument the CLI aborted
  outright (`input()` → EOFError), and with one it silently installed the **default stack without
  asking a single question**. `commands/init.md` now instructs Claude to interview the user in chat
  (AskUserQuestion; all 7 questions incl. the capture privacy note), write a temp `init.yaml`, and
  run `init --config <file>` non-interactively — or pass through `--defaults`/`--config` verbatim
  when given. The CLI probe chain also gains the third console script (`claude-sdlc`), and
  `cli.py`'s target-path prompt is now EOF-tolerant (falls back to `.` like every other prompt
  instead of aborting). README's quickstart claim updated to match, plus a worked `init.yaml`
  example — the `--config` schema was previously documented only in source.
- **Docs-truth sweep** (every number re-verified on disk before fixing): the README said **35**
  rules per profile and "**10** overlay rule sets" — reality is **36** installed for the default
  React+FastAPI+PostgreSQL stack and **13** overlay rule files; `docs/architecture.md` said **24**
  rules in two places (25 exist); `docs/launch/road-to-1.0.md` hardcoded **v0.57.0** (now points at
  the CHANGELOG so it can't drift); `/claude-kit:abort` was missing from both command lists (README +
  architecture) — a user whose run went sideways had no documented escape hatch; the README init-flow
  list stopped at 6 questions while `init` actually asks 8 — the undocumented two now listed are
  **learning capture** (with its privacy note and the `CLAUDE_KIT_NO_AUTOCAPTURE=1` opt-out) and
  **usage scope** (organization scope asks four follow-ups); new troubleshooting row for
  `pip install claude-kit` → the package is **`claude-code-kit`**; and `claude-kit --help` no longer
  advertises the experimental `research` group whose only command is hidden (it now hides with it).

- **`orchestrator`** — dropped `permissionMode: plan`, granted `Write`/`Edit`, and added an explicit
  **write-confinement hard rule**: state and gate evidence only (`.claude/CONTINUITY.md`,
  `.claude/state/`, `.claude/artifacts/`, and gate reports handed back by read-only reviewers) —
  never source code, tests, configs, or feature docs. The orchestrator is now the declared **scribe**
  for read-only gate agents: it persists their returned reports verbatim and records their verdicts /
  durable lessons on their behalf. "Never writes code" remains a hard rule.
- **`incident-responder`** — dropped `permissionMode: plan`, granted `Write`/`Edit` confined to the
  incident log (`docs/incidents/`) and `CONTINUITY.md`. Its charter (keep the running log current at
  every status change) was impossible read-only; mitigation stays delegated and human-gated.
- **Read-only gates made honest instead of self-contradictory** — `secret-scanner`,
  `owasp-reviewer`, `policy-validator`, `dependency-scanner`, `security-reviewer`,
  `devils-advocate`, `merge-reviewer` (and the postgres overlay `db-performance-reviewer`) keep
  `permissionMode: plan`, but every "write your report to `docs/…`" / "log to CONTINUITY.md" /
  "promote to agent-memory" mandate is rewritten as **return-in-handoff**: the spawner
  (security-reviewer → Orchestrator) persists reports and learnings for them.
- **`dependency-scanner` no longer installs tooling** — the METHOD's `pip install pip-audit` line
  (a mutation its own CONSTRAINT 3 forbids and plan mode blocks) is replaced with
  use-only-if-present + degrade-to-manifest-review, matching the kit's degrade-to-no-op posture.

### Not adopted (deliberately)

- **Compressing the orchestrator prompt to ~350 lines** (suggested by the review alongside the
  gate-set fix) — refused: the verified defects were ghosts, missing wiring, and unconditioned
  gates, not length. Every remaining section is load-bearing (wave mode, defect loop, health
  monitoring, skill routing); the fix *added* ~60 lines of correctness rather than deleting
  content to hit an arbitrary number.
- **Granting Write to the security scanners/reviewers** so they could keep writing their own
  reports — read-only gates are a design asset (a reviewer that can edit the code it reviews is a
  weaker gate); the scribe pattern preserves the artifact trail without weakening the boundary.
- **Routing orchestrator state through a new `ckit-state` helper binary** — the plan-mode block
  applies to mutating Bash too, so a CLI detour would not have fixed the contradiction; a direct,
  confined Write grant is simpler and matches how the kit already trusts `developer`/`pr-raiser`
  with `acceptEdits`.
- **`owasp-reviewer` `opus` → `sonnet`** (suggested by the review) — refused: `model-tiers.md` §Notes
  already documents keeping it `opus` for vulnerability reasoning as a deliberate exception to its
  `sonnet` sibling scanners. A reviewer suggestion doesn't outrank a documented decision.
- **Dropping `Edit` from `tester`/`senior-tester`** — refused: they author test artifacts and
  fixtures; the grant is load-bearing. No evidence of misuse was presented.
- **Rewriting `.claude/skills/_references/…` links as relative `../_references/` paths** (the review
  claimed the hardcoded form "breaks in plugin context") — refused: `scaffold.py` installs
  `_references/` at exactly that canonical path *on purpose* (its own comment says so), and prose
  paths are resolved against the project CWD, so the relative form would break the scaffolded
  install — the primary context — to serve plugin-without-init sessions where *every* `.claude/`
  reference (rules included) dangles equally. That's the documented plugin+init model, not a
  path-style bug.
- **The `skills: stack-relevant` profile value itself** — deferred with its premise corrected by
  measurement (see the mapping table in `docs/skill-audit.md`): lane-based filtering yields a ~4%
  reduction for the default stack because 26 of the 48 collection skills encode infrastructure
  choices no stack question captures. Shipping the profile value anyway would have added a resolver
  special-value and a `stacks.yaml` mapping that silently delivers almost nothing for most users.
  The meaningful version requires an infra axis at init (Kafka? Temporal? GCP? k8s?) — a feature
  design left for a deliberate future pass, with the measured table as its input. `skills: all`
  stays the enterprise default, trade-off documented.
- **All four hooks-modernization claims from the industry review** (re-verified against the
  official hooks reference + the anthropics/claude-code changelog after the original research
  agent died unverified): **(1) exec-form hook commands** (`args: [...]`) — refused *for now*:
  docs-recommended for path placeholders, but introduced only in Claude Code **2.1.139**; on any
  older version an `args` entry degrades to bare `bash` consuming hook JSON on stdin — every guard
  silently dead — while the kit's double-quoted shell form is already space/char-safe. Revisit
  when the floor ages. **(2) `permissionDecision` JSON outputs with auto-allow for read-only
  commands** — mechanism verified real, adoption refused: exit-code-2 blocking remains a fully
  supported signaling path (only *top-level* decision/reason is deprecated, PreToolUse-only), the
  JSON form adds a stdout-purity constraint to every bash guard for zero behavioral gain, and a
  plugin auto-*allowing* commands would loosen the user's own permission posture from inside a
  dependency. **(3) anchored `^name$` matchers** — refuted by the docs: matchers made only of
  exact-match-set characters (`Bash`, `Read`, `Edit|Write`) are compared as exact strings, not
  unanchored regexes; anchoring would move them onto the regex path for nothing. (Related
  observation recorded: exact matching means `Edit|Write` does not cover `NotebookEdit` — left
  as-is; no notebook overlay exists to warrant it.) **(4) a prompt-type Stop gate** — refused:
  the product ships `/goal` as exactly that (a built-in session-scoped prompt-based Stop hook,
  8-consecutive-block cap); an always-on plugin Stop gate would tax every turn of every user with
  a model call to duplicate it. Documented `/goal` instead.
- **Splitting `manual-test` (516 lines) and the five oversized stack-collection SKILL.md files**
  (`docker-compose` 606 · `grafana-dashboards-and-alerts` 535 · `containerization-and-deployment`
  534 · `langfuse-llm-tracing` 508 · `redis-caching-patterns` 505) — deferred, not rushed:
  `manual-test` is 3% over the ~500-line guidance and a split costs more cohesion than it buys;
  the collection five deserve one measured sweep of their own. Claim correction recorded: the
  review's "no references/ split" was false for the collection (20+ skills already ship
  `references/`) — it was true only of `security-and-hardening`.



**Wave orchestration — program-scale runs, explicit skill routing, and the inventory-approval
pattern.** Adopts the program-management patterns from Ryan Carson's public writeup of a
40-session orchestrated migration (one pure orchestrator, audit-first frozen manifest, risk-ordered
waves, disjoint file boundaries, gate-runner sessions, propose-inventory/human-approves,
stop-and-report escalation, docs-as-final-wave) into the `/sdlc` pipeline. Stack-agnostic,
catalog untouched. **+1 core rule (24 → 25); 0 new agents/skills.**

### Added

- **`rules/wave-orchestration.md`** (new core rule, installed by every profile). Program mode for
  migration-scale work: Wave 0 parallel read-only audits synthesized into **one frozen scope
  manifest** committed to the repo (every unit gets a verdict + wave number; `UNKNOWN` = stop and
  ask; no worker re-litigates scope); waves sequenced by **risk, not convenience** (irreversible
  steps last, restore-point git tags); **disjoint file boundaries** stated in every parallel worker
  prompt; **gate-runner workers** between waves (regression suite on an isolated branch, backup
  audit + fresh snapshot before destructive waves); the **inventory pattern** for irreversible steps
  (approve the list, not the idea); a pre-declared **escalation path** (workers stop and report,
  never improvise); and a mandatory **knowledge-closeout wave** (docs/rules/skills/agent memory
  updated to the new state of the world).
- **`orchestrator` Mode E — Program / Wave Mode.** New classification (`program-scale`: > ~20
  files / multiple subsystems, or any irreversible step) and the wave pipeline above, plus three new
  orchestrator sections: **Skill Routing** (every spawn prompt names the skill(s) the worker must
  load for its stage — spec → `spec-driven-development`, implementation → `incremental-implementation`
  + lane overlays, closeout → `refresh-docs`/`remember`/`consolidate-learnings`, etc.; absent skills
  drop silently), **Model Tiering** (cheap tier for audits/sweeps/scans, standard for build/review/
  gates, top tier only for orchestration/hard reasoning, per `rules/model-tiers.md`), and an
  **Escalation Protocol for Workers** (stop, report to the orchestrator, don't improvise; overrides
  recorded in the manifest/CONTINUITY). Orchestrator rules 19–23 pin all of it.
- **`rules/human-in-the-loop.md` — "approve the inventory, not the idea."** Destructive/irreversible
  asks must be inventory-shaped: dry-run list + counts proposed, the human approves that exact list,
  the agent executes exactly it and re-verifies counts; deviations stop and re-enter the protocol.

### Changed

- **`skills/sdlc/SKILL.md`** — classification now includes `program-scale` → Mode E;
  `wave-orchestration.md` added to the load-the-contract list; new step 3 makes skill routing and
  per-worker model tiering an explicit orchestrator instruction on every run.
- **`rules/mandatory-workflow.md`** — the "Which Workflow?" table routes migration-scale /
  irreversible work to `wave-orchestration.md` (units inside a wave still run the bug-fix or
  feature workflow).
- **`orchestrator` parallelism rules** — explicit **disjoint file boundaries are now mandatory for
  every parallel spawn in every mode**, not just an early-intervention health signal.
- Docs/counts: README, `CLAUDE.md`, `docs/architecture.md`, `docs/skill-audit.md` updated for the
  25-rule core.

## [0.57.0] — 2026-07-03

**Adoption & hardening — release automation, honest docs, and a credibility pass.** No new
capability and no change to the core promise: configuration-only SDLC scaffolding for Claude Code, no
application code, no Docker, stack-agnostic core, catalog-driven. This release closes the gap between
"published to PyPI" and "tagged/released on GitHub," adds an honest release + road-to-1.0 policy, audits
the skill surface, and tightens the README so every claim is verifiable. **0 new agents/skills/rules;
`catalog.resolve()` and `catalog/*.yaml` untouched.**

### Added

- **Automated git tag + GitHub Release on publish.** `publish.yml` gains a `github-release` job that,
  after a successful PyPI publish, creates the `vX.Y.Z` tag and a GitHub Release whose body is that
  version's `CHANGELOG.md` section. Idempotent (a re-run over an already-released version is a no-op) and
  downstream of `publish` (a Release is only cut once the wheel is actually on PyPI).
- **`scripts/backfill-releases.sh` (`--dry-run`).** One-off, idempotent backfill that retroactively
  creates the tag + Release for past versions that shipped via merge-to-main before the automation
  existed. Anchors each tag to the commit that introduced that version into `pyproject.toml` (git
  pickaxe), and skips — with a warning — any version whose release commit can't be located.
- **[`docs/RELEASE-POLICY.md`](docs/RELEASE-POLICY.md).** Versioning, latest-only support, the
  five-place version bump + CHANGELOG, and the publish/tag/Release automation, in one place.
- **[`docs/launch/road-to-1.0.md`](docs/launch/road-to-1.0.md).** An honest, verifiable list of what
  stands between the current `4 - Beta` and 1.0 (stack coverage, enforcement honesty, hook portability,
  evidence base, export fidelity, API stability). The Development Status classifier stays `4 - Beta`.
- **[`docs/skill-audit.md`](docs/skill-audit.md).** Core-vs-collection classification, the per-profile
  install footprint (agents/skills/rules + an on-disk token estimate), and the finding that the
  `enterprise` profile's `skills: all` installs every collection skill regardless of the chosen stack.
  Documents and recommends; changes no profile (skills load on demand, so this is selection, not
  always-resident context).
- **Launch-prep assets under `docs/launch/`** (owner checklists, not code): `github-about.md`,
  `demo-script.md`, `directory-submission.md`, `awesome-prs.md`, `posts.md`, and `seed-issues.md`.

### Changed

- **README credibility pass.** Strengthened the anti-sycophancy / evidence framing and added a
  "What loads into your context" per-profile table (agents/skills/rules), so the footprint is explicit
  before install. Counts remain pinned by `scripts/check_docs_consistency.py`.

### Not adopted (deliberately)

- **No version-parity CI addition** — `scripts/check_docs_consistency.py::check_versions()` already
  enforces parity across the four manifests, `SECURITY.md`, and the latest CHANGELOG heading.
- **No `profiles.yaml` change** for the `skills: all` finding — flagged and recommended in the audit;
  any opt-in must stay a catalog/config change with no `resolve()` branching (golden rule #6).
- **Development Status stays `4 - Beta`** — the classifier is not flipped until the road-to-1.0 gaps
  are met.

## [0.56.0] — 2026-07-01

**`export` command — carry the config to Cursor / VS Code / GitHub Copilot.** A teammate who works in
an editor that isn't Claude Code can't consume `.claude/` or run the gated `/sdlc` pipeline. `claude-kit
export` projects the **same resolved plan** into the formats those single-agent editors read natively,
so claude-kit's standards travel even where the pipeline can't. No change to the core promise —
configuration-only SDLC scaffolding for Claude Code, no application code, no Docker, stack-agnostic
core, catalog-driven. **0 new agents/skills**; `catalog.resolve()` untouched (a pure projection of the
existing plan).

### Added

- **`claude-kit export [path] -t cursor|agents|copilot`.** Re-targets the resolved `ResolvedPlan` to:
  - **`cursor`** — `.cursor/rules/*.mdc` (one per rule, with YAML frontmatter derived generically from
    each rule: `description` = H1 + lead sentence; `alwaysApply: false` for the on-demand rule set;
    overlay rules get `globs` keyed on the plan's *language/database* values — `typescript` →
    `**/*.ts,**/*.tsx`, `python` → `**/*.py`, `postgres` → `**/*.sql`, …), an always-applied
    `000-project.mdc` charter, and `.cursor/mcp.json` (the `type` discriminator stripped for Cursor).
  - **`agents`** — a root `AGENTS.md` (charter + single-agent SDLC checklist + rule index + fidelity
    note); read by both Cursor and Copilot.
  - **`copilot`** — `.github/copilot-instructions.md` (the same synthesized document as `agents`).
- **Honest fidelity, everywhere.** Rules, the project charter, and MCP port cleanly; the **enforced**
  quality gates, independent reviewer subagents, and automated defect loop are Claude-Code-only and are
  exported as a single-agent **self-check checklist**. Every exported document states this explicitly
  (a "What ports from Claude Code — and what doesn't" note + the workflow guide's opening).
- **Flags mirror `init`:** `--dry-run` (report, write nothing), `--force` (refresh in place; otherwise
  a hand-edited file is preserved and the new version lands beside it as a `.claude-kit` sidecar),
  `--config`/`--defaults` (resolve a fresh selection instead of the project's installed one), `--json`.
- **New payload template** `templates/export/sdlc-workflow-guide.md.tmpl` (stack-agnostic; renders with
  the project's real test/lint/build commands), plus `tests/test_export.py` and
  [`docs/cursor-export.md`](docs/cursor-export.md) (usage + the full fidelity matrix).

## [0.55.0] — 2026-07-01

**React overlay rules split under Claude Code's 40k memory limit.** Two React design-system overlay
rules shipped over the 40,000-character memory/rule-file limit, so every React scaffold saw the
`over the 40.0k-char limit · /memory` warning and risked the rule loading only partially. They are now
split by concern — 100% of content preserved verbatim — and a CI guard keeps any rule from regressing.
No change to the core promise — configuration-only SDLC scaffolding for Claude Code, no application
code, no Docker, stack-agnostic core, catalog-driven. **0 new agents/skills.**

### Fixed

- **Oversized React overlay rules split under the 40k limit.** `ui-design-system.md` (56.7k) → the
  foundations/index `ui-design-system.md` + `ui-components.md` (cards, badges, buttons, form controls,
  states, tooltips, KPI labels, data tables, compound components) + `ui-layout-and-motion.md` (page
  layout, motion, accessibility, page blueprints, quick reference); `ux-patterns.md` (44.4k) → the
  content/interaction `ux-patterns.md` + `ux-dashboard-patterns.md` (chart standards, tab bar, KPI-grid
  layouts, global filter strip). Every shipped rule file is now well under the limit. The React
  `overlay_rules` list (`catalog/stacks.yaml`) grows 5 → 8; cross-references in `react-patterns.md`,
  `mobile-design-guidelines.md`, and `design-system-compliance.md`, and the `ui-ux-design` /
  `component-design` skills + `ui-designer` agent, all repoint to the split files.

### Added

- **`scripts/check_rule_sizes.py` regression guard.** Scans every shipped rule file (`rules/*.md`,
  `templates/stacks/**/rules/*.md`, `templates/org/rules/*.md`) and fails if any reaches 38,000
  characters (2k of headroom under the 40k hard limit). Wired into CI next to the MCP-pin gate and
  covered by `tests/test_rule_sizes.py`.

## [0.54.0] — 2026-06-29

**Safety, correctness, and capability hardening pass.** Two reviews (a fresh practical review and an
external improvement brief) converged on a set of gaps; every premise was verified against the source
before acting. No change to the core promise — configuration-only SDLC scaffolding for Claude Code, no
application code, no Docker, stack-agnostic core, catalog-driven, evidence-backed gates, safe upgrades.
**0 new agents/skills.**

### Security

- **Learning capture is privacy-hardened (still on by default).** `capture-learnings.sh` now excludes
  secret-bearing files (`.env`, `*.pem`/`*.key`, `credentials.*`) from the changed-file list, redacts
  leaked-credential value shapes (private keys, `AKIA…`, `sk_live_…`, Slack/GitHub tokens) from
  anything handed to the background job, bounds the payload with env-overridable
  `CLAUDE_KIT_CAPTURE_MAX_LINES` / `CLAUDE_KIT_CAPTURE_MAX_BYTES`, and instructs the job never to record
  secrets/PII. `init` prints a privacy notice (and a jq-missing caveat); `doctor` warns while capture is
  wired; the same caveat is documented in `SECURITY.md` and the project README.
- **No raw slash-command argument interpolation.** `/claude-kit:init` no longer interpolates the
  textually-substituted `$ARGUMENTS` into any executable shell block; the agent runs the CLI with the
  user's arguments as separate, individually-quoted argv items. A CI test fails on `$ARGUMENTS` inside a
  command's fenced code block.
- **Git guards hardened** against global-option and refspec bypasses (`git -c …` / `git -C …`,
  `+main`, refspec forms); manual-stdin guards no-op on a TTY.

### Added

- **Command discovery (`detect.py`).** `init`/`upgrade` inspect a populated target for unambiguous
  package-manager signals and wire the real commands into `CLAUDE.md` — JavaScript (npm·pnpm·yarn·bun)
  install + present `package.json` scripts, Python (uv·poetry·pdm·hatch) install. Fail-open and
  conservative (an empty target is a no-op, preserving `init --dry-run` ≡ a real install).
  `--detect-commands` / `--no-detect-commands` opt in/out; recorded in the stack snapshot.
- **Transactional upgrade journal.** `upgrade` writes `.claude/config/upgrade-in-progress.json` before
  mutating and clears it after the new baseline commits; combined with convergent render-and-compare, an
  interrupted upgrade is finished and cleared by the next run. `doctor` warns while a journal is present;
  it is gitignored. `merge_install` is not journaled.
- **JSON Schema validation** for the catalog and persisted artifacts (`jsonschema` is an optional
  `[schema]` extra; a no-op when absent). Wired into `validate --strict` and the catalog check.
- **`--json` output** for `validate`, `doctor`, `diff`, `status`, `pipeline validate|status`, and
  `init --dry-run` via a structured `report` module (human output unchanged).
- **MCP pin freshness tooling** — an offline CI gate that fails on `@latest`/unpinned servers, plus a
  scheduled workflow that opens a tracking issue when a pin falls behind the registry.

### Changed

- **`lint-fix.sh` scopes to changed files by default** (git diff vs HEAD + untracked), so a Stop hook
  never reformats files the user didn't touch. `CLAUDE_KIT_AUTOFIX=1` restores whole-repo formatting;
  falls back to whole-repo when git is unavailable.
- **Planned CLI commands are hidden** from `--help` unless `CLAUDE_KIT_EXPERIMENTAL=1` (still marked
  `[planned]`, still exit non-zero) so they can't be mistaken for working features.
- **Skill/agent descriptions** front-load their triggers and fit the picker cap; a warn-only CI check
  reports any that exceed it.

### Docs

- New `docs/KNOWN_LIMITATIONS.md` (guards are best-effort, not a security boundary; command discovery
  scope; non-atomic first install; convergent/journalled upgrades) + a README "Who this is for" section
  and reconciliation/reference fixes.

## [0.53.0] — 2026-06-28

**Adopt the verified wins from an exhaustive review of three GitHub orgs — `Netflix`, `aws`, and
`apple`** (all **1,214** public repos: Netflix 234 · aws 549 · apple 431). Every repo was surveyed (34
agents over every page across the three orgs — no repo skipped), candidates deep-read for license +
transferable practice, and the shortlist **adversarially verified** against the live source. These orgs
are overwhelmingly SDKs, CLIs, cloud-product code, and running services with nothing transferable to a
config scaffolder — but the review surfaced a real **gap**: the kit had `agent-resilience` (the coding
agent's own retries) yet **no service-level resilience rule at all**. **7 adoptions across the three
orgs; 1 new rule (`resilience-engineering`), the rest extensions to existing files — 0 new
agents/skills** (skill counts unchanged at 104/56/48; MCP fragments unchanged at 17; **core rules
23 → 24**). Everything re-derived **in prose, never vendored**; all sources Apache-2.0 or MIT/Apache-2.0.

A note on method: the per-repo deep-dive initially skipped several famous repos on "the source is a
library/tool, not documentation" grounds — but the kit ships *prose*, so a Java library or a C++ database
is a perfectly valid *source* for a re-derived discipline. The adversarial-verify pass (one skeptic per
item, reading the live README + license) judged the **discipline**, not the artifact type, and confirmed
all seven hold, are stack-agnostic, genuinely new, and permissively licensed.

Rules:

- **`resilience-engineering.md`** (NEW — the kit's first service-level resilience rule, explicitly
  distinct from `agent-resilience.md`, which is about the coding agent's own machinery). Three sections:
  (1) **stability patterns** at every remote-call boundary — timeout + deadline budget, retry with
  budget/jitter, circuit breaker, bulkhead/isolation, backpressure, load shedding, graceful
  degradation — plus **adaptive concurrency limiting** (TCP-congestion-control + Little's Law to find the
  limit from latency instead of hand-tuning it, server- and client-side, with priority partitioning;
  from the Apache-2.0 `Netflix/concurrency-limits`); (2) **distributed-time correctness** — never compare
  raw wall-clocks across nodes; treat "now" as a `[earliest, latest]` interval and commit-wait for
  cross-node ordering (from the MIT/Apache-2.0 `aws/clock-bound` + Google TrueTime); (3) **chaos
  engineering** — steady-state hypothesis, vary real-world events, minimize blast radius with an automated
  abort, prefer production, run continuously (from the Apache-2.0 `Netflix/chaosmonkey` + Principles of
  Chaos).
- **`devops-observability.md`** — a **failure-domain-aware progressive rollout** section: update one
  failure domain (zone/region/rack/cell/shard) at a time to contain blast radius, accelerate in
  exponential batches with a readiness gate between them, roll back newest-first to escape a bad revision
  fastest, and pause-on-alarm automatically (from the Apache-2.0 `aws/zone-aware-controllers-for-k8s`).
- **`testing.md`** — a **Deterministic Simulation Testing** section for concurrency/distributed-system
  bugs: funnel all nondeterminism (clock, RNG, scheduling, IO, network) through injectable seams, drive
  the system from a single seed in single-threaded virtual time so a failing run replays bit-for-bit, and
  inject faults aggressively in-sim (the "buggify" idea); complements fuzzing + property-based testing
  (from the Apache-2.0 `apple/foundationdb`).

Skills:

- **`spec-driven-development`** — a third proposal mode beyond full-spec and delta-spec: an **RFC track**
  for one-way-door changes (public/cross-service APIs). Adds working-backwards artifacts (write the future
  CHANGELOG/README first), a designated API **bar-raiser** with interface veto, a staged lifecycle
  (feedback → final-comment → API sign-off → implementation planning), and separation of API approval from
  implementation approval (from the Apache-2.0 `aws/aws-cdk-rfcs`).
- **`security-and-hardening`** — a **Continuous Least-Privilege** section: least privilege is a decay
  loop, not a one-time grant — periodically audit which grants/scopes/roles were *actually exercised* over
  a trailing window, auto-revoke the unused, snapshot policies for fast rollback, and keep an exempt-list
  for break-glass access (from the Apache-2.0 `Netflix/repokid`).

Docs/counts: core rules **23 → 24** across `README.md` (5 anchors), `CLAUDE.md`, and
`docs/architecture.md`; `agent-resilience.md` cross-links the new service-level rule (and vice versa); a
new Influences row + depth blurb (kept to the latest three reviews — the microsoft 0.50 blurb rolls off).

What we **did not** add (already covered, or fails the bar): `Netflix/chaosmonkey`-the-tool,
`Netflix/dispatch` (archived incident-management *app* — covered by `incident-postmortem` +
`incident-responder`), `Netflix/maestro` (a workflow-orchestration *platform*, like Airflow/Temporal —
a tool to use, not a practice), `Netflix/security-bulletins` (disclosure output, covered by the security
layer); the AWS service/SDK material — `aws-sam-cli`, `aws-pdk`, `aws-lakeformation-best-practices`,
`aws-networking-best-practices`, `aws-sam-cli-pipeline-init-templates`, `device-storelibrary-cpp`,
`mcp-proxy-for-aws` (AWS-IAM auth transport, not a tool-exposing MCP server); and `apple`'s
`apple-root-program` (PKI/CA policy, no license), `batch-processing-gateway` (a Spark-on-K8s service), and
`pkl-evolution` (a language-evolution RFC — redundant with the richer `aws-cdk-rfcs` RFC track adopted
above).

## [0.52.0] — 2026-06-28

**Adopt the verified wins from an exhaustive review of the entire `facebook` (Meta) GitHub org** (all
**168** repos — Meta long ago spun React, PyTorch, Jest, etc. into dedicated orgs, so the `facebook` org
itself is small). Every repo was surveyed (7 agents over every page — no repo skipped), candidates
deep-read for license + transferable practice, and the shortlist **adversarially verified** against the
live source. The org is almost entirely libraries/frameworks/language-tooling with nothing transferable
to a config scaffolder, and several famous repos were **already covered** (`infer` by the 0.51
compile-time-logic-bug lint layer; React by the kit's React overlay; testing by an already-deep
`testing.md`). The verify pass *dropped* the weak picks — `DNE-TaaC` (datacenter network-device testing,
1★, overlaps the config-driven skills) and `mbt` (a 0★ Meta-service-specific binary-transparency client;
that practice belongs to Sigstore/Certificate-Transparency, not this org). **3 adoptions, all extensions
to existing rules — 0 new agents/skills/rules** (skill counts unchanged at 104/56/48; MCP fragments
unchanged at 17). All sources MIT / Apache-2.0.

Rules:

- **`linting-and-formatting.md`** — a new **Interprocedural Taint / Data-Flow Analysis** layer: declare
  untrusted **sources**, dangerous **sinks**, and **sanitizers**, then trace data flow *across function
  boundaries* and flag any unsanitized source→sink path — distinct from the single-line Security-Lint
  layer and the Compile-Time Logic-Bug layer, and the automated codebase-wide complement to
  `security-and-hardening`'s secure-by-construction wrappers (from the MIT `facebook/pyre-check`/Pysa and
  `facebook/mariana-trench`; engines: Pysa/Mariana Trench/CodeQL/Semgrep).
- **`devops-observability.md`** — a **continuous performance-regression CI gate**: run the baseline
  (control) and the PR commit (treatment) **concurrently on the same machine** to cancel environmental
  variance, and gate on the **relative delta** (with a tolerance band) rather than an absolute number —
  catching the gradual regressions the one-shot Load-vs-SLO gate misses (from the Apache-2.0
  `facebook/FAI-PEP`).
- **`agent-guardrails.md`** — extended §4's sandbox **policy** with **defense-in-depth enforcement**:
  L1 policy decision (existing) + L2 argument validation at the boundary (path canonicalization,
  injection screening, response sanitization) + L3 OS-level runtime backstop (eBPF-LSM/seccomp
  intercepting `open`/`connect`/`exec`) so a tool that ignores the declarative policy still cannot escape
  scope (from the MIT `facebook/mcpguard-dynamic`).

What we **did not** add (already covered, or fails the bar): `infer`/`mariana-trench`-as-a-tool and
`sapp` (the kit's compile-time-logic-bug + new taint layer cover the discipline); `fbt` i18n (JS-specific,
archived); `memlab` (JS-only heap analysis); `Ax` (ML hyperparameter optimization, a library);
`chef-cookbooks`/`IT-CPE`/`taste-tester` (Chef IaC / IT fleet management); `ThreatExchange`/`threat-research`
(content-moderation / CTI data, out of SDLC scope); `akd`/`private_processing` (domain-specific crypto
libraries); plus the dropped `DNE-TaaC` and `mbt`.

## [0.51.0] — 2026-06-28

**Adopt the verified wins from an exhaustive review of the entire `google` GitHub org** (all **2,881**
repos). Every repo was surveyed (60 agents over every page — no repo skipped), the top ~300 candidates
deep-read for license + transferable practice, and the shortlist **adversarially verified** against the
live source. The verify pass *dropped a third* of the shortlist: `deps.dev` (a REST/gRPC API, **not** an
MCP server), `licensecheck` (license *classification*, not the claimed compatibility gate), the
Go/Rust/C++-locked tools `capslock` · `rust-crate-audits` · `fuzztest` · `libprotobuf-mutator` (not
re-derivable stack-agnostic), `sqlcommenter` (archived → donated to OpenTelemetry), and `ax` (too early —
"major breaking changes prior to stable"). Everything is re-derived **in prose, never vendored**; all
sources Apache-2.0 / BSD-3-Clause / MIT except one CC-BY-4.0 book (concept-only). **21 adoptions, all
extensions to existing files — 0 new agents/skills/rules** (skill counts unchanged at 104/56/48); only the
**MCP fragment count rises 13 → 17**.

Rules:

- **`human-in-the-loop.md`** — a new **multi-party authorization** section: the two-person rule for the
  highest-stakes actions, context-bound (multi-factor) approval, and **breakglass-with-auditing** (loud
  emergency override + mandatory after-the-fact review), extending the simple approval gate beyond a
  single approver (concept-only from the CC-BY-4.0 *Building Secure & Reliable Systems*,
  `google/building-secure-and-reliable-systems`).
- **`testing.md`** — four techniques beyond example-based tests: **parameterized/table-driven** tests
  (`google/patrick`); **semantic-equality & structured-diff** assertions, float tolerance over brittle
  deep-equality (`google/go-cmp`); a **Fuzzing** section — coverage-guided + structure-aware + **continuous
  fuzzing as a CI gate** (`google/atheris` · `google/honggfuzz` · `google/clusterfuzzlite`); and
  **parallel execution + repeated-run flakiness detection** (`google/gtest-parallel`).
- **`linting-and-formatting.md`** — a **compile-time logic-bug analysis** layer (find bugs the type
  checker accepts — `google/error-prone`), **license-header enforcement** as a check-mode CI gate
  (`google/addlicense`), and **deterministic block sorting** via marker comments to cut merge conflicts
  (`google/keep-sorted`).
- **`devops-observability.md`** — **multi-window burn-rate alerting** (alert on error-budget burn across
  paired short/long windows, not raw error rate — `google/prometheus-slo-burn-example`) and **high-volume
  logging** patterns (call-site rate-limiting + lazy argument evaluation — `google/flogger`).
- **`reasoning-techniques.md`** — **prompt-as-code**: treat a reusable prompt as a versioned, schema-validated,
  testable artifact (`google/dotprompt`).
- **`tool-design.md`** — the §8 atomic-state note gains the **atomicity-vs-durability** nuance
  (fsync-before-rename, same-filesystem, temp cleanup — `google/renameio`).

Skills:

- **`security-and-hardening`** — **reproducible-build verification** (independent rebuild → normalize
  benign differences → attest equivalence — `google/oss-rebuild`); **source-level missing-patch detection**
  for vendored/forked code via OSV-derived signatures (`google/vanir`); **secure-by-construction injection
  defense** (compile-time-constant query text + typed trusted/untrusted wrappers — `google/safe-active-record`
  · `google/mug`); **archive-extraction safety** (zip-slip / symlink — `google/safearchive`); and **ReDoS
  defense** for untrusted regex input (`google/re2`).
- **`context-engineering`** — a **Long-Document Extraction** section: overlapping chunks → parallel
  schema-constrained passes → source-interval grounding → multi-pass recall (`google/langextract`).
- **`performance-optimization`** — a **statistical browser benchmarking** discipline: interleaved repeated
  sampling, 95 % confidence intervals, auto-sample-until-significance (`google/tachometer`).
- **`api-integration`** — a **record-replay** pattern for deterministic external-API tests (record real
  responses with secrets redacted → replay offline → re-record on drift — `google/test-server`).

Catalog:

- **`catalog/mcp.yaml`** — **4 first-party Google Security Operations MCP fragments** (one upstream repo,
  `google/mcp-security`, Apache-2.0): **secops** (Chronicle SIEM), **gti** (Google Threat Intelligence /
  VirusTotal), **scc** (Security Command Center / cloud posture), **secops_soar** (SecOps SOAR) — the
  SOC/operational-security capability domain the catalog had no entry for. Run via pinned `uvx`; each needs
  a paid Google SecOps backend + ADC and is **referenced, never bundled** (like `sentry`/`repowise`).

What we **did not** add (already covered, or fails the bar): property-based testing (already in
`test-driven-development` §property-based, 0.38) — the new Fuzzing section builds on it; pre-add dependency
evaluation (already `library-review` + `dependency-verification`); SBOM/CVE supply-chain (already
`security-and-hardening`, 0.39/0.50); the dropped shortlist items above.

## [0.50.0] — 2026-06-28

**Adopt the verified wins from an exhaustive review of the entire `microsoft` GitHub org** (all **8,147**
repos). Every repo was surveyed (165 agents, one per 100-repo page — no repo skipped), the top candidates
deep-read for license + transferable practice, and the shortlist **adversarially verified** against the
live source. The signal concentrated in agentic-AI engineering, exactly where the kit's agent-operation
rules were thinnest. Everything is re-derived **in prose, never vendored**, all sources MIT (one
CC-BY-4.0 doc, concept-only). **18 adoptions, all extensions to existing files — 0 new agents/skills/rules**
(skill counts unchanged at 104/56/48); only the **MCP fragment count rises 9 → 13**.

Rules:

- **`agent-guardrails.md`** — expanded the one-line OWASP stub into the full **Agentic Top-10
  (ASI01–ASI10, 2026)** taxonomy mapped to the kit's existing layers (from `microsoft/agent-governance-toolkit`);
  turned "sandbox shell/code execution" into a declarative **sandbox policy schema** (fs/network/resource
  scope, fail-closed, runtime-updatable — from `microsoft/mxc`); added **layered prompt-injection defense**
  (spotlighting/delimiter-marking, signature screen, task-drift check — from `microsoft/llmail-inject-challenge`).
- **`evals.md`** — §3 gains **multi-judge assemblies + super-judge** aggregation and the
  **tool-use-vs-response-quality** split (from `microsoft/llm-as-judge` · `microsoft/EvalsforAgentsInterop`);
  new §8 **"Evaluate multi-turn behavior"** (task-sharding, single-vs-multi-turn degradation — from
  `microsoft/lost_in_conversation`).
- **`reasoning-techniques.md`** — added **validator-in-the-loop** (generate → run the real checker → feed
  errors back) and **dynamic few-shot + Medprompt ensembling** (from `microsoft/dsl-copilot` · `microsoft/promptbase`).
- **`human-in-the-loop.md`** — a new **"Implementing the gate"** section (declarative approval gates,
  resumable/out-of-band approval, fail-safe timeout, audit trail — from `microsoft/agents-humanoversight`).
- **`linting-and-formatting.md`** — a **Security Lint Layer** (ban dynamic-eval, raw-HTML sinks, insecure
  randomness, disabled-TLS, shell-from-input as pre-commit errors — from `microsoft/eslint-plugin-sdl`).

Skills:

- **`threat-model`** — a **"Red-team the model feature"** section: multi-turn adversarial strategies,
  scorer-driven Attack-Success-Rate, continuous re-runs (from `microsoft/PyRIT`).
- **`security-and-hardening`** — an **SBOM generation** practice (SPDX/CycloneDX as a release artifact,
  distinct from CVE audit — from `microsoft/sbom-tool`).
- **`context-engineering`** — a 4th primitive, **priority-based prompt composition/pruning** (from
  `microsoft/vscode-prompt-tsx`).
- **`code-review-and-quality`** — **quantified-lines PR sizing** (exclude generated/whitespace/comment
  lines, weight by reviewability, calibrate to the repo — from `microsoft/PullRequestQuantifier`).

Catalog — 4 first-party MCP fragments added to `catalog/mcp.yaml` (9 → 13):

- **MS Learn Docs** (`ms_learn`, hosted HTTP, no auth) · **Azure** (`@azure/mcp`) · **Azure DevOps**
  (`@azure-devops/mcp`) · **Wassette** (WASM-sandboxed tool execution — the concrete backend for the
  guardrails sandbox requirement).

**Deliberately NOT added** (the verify pass earned its keep): `ToolTalk` (its ground-truth-tool-sequence
grading *contradicts* `evals`' "grade outcomes, not paths"); `prompty` (an LLM-app product, not a
transferable SDLC practice); `markitdown`, `autogen` (maintenance-mode + CC-BY-4.0), and `playwright-mcp`
(already in the catalog). New **Rust** (`oxidizer`) and **.NET/WinUI** (`win-dev-skills`) stack overlays
were surfaced and deferred to their own future PRs. Version 0.49.0 → 0.50.0.

## [0.49.0] — 2026-06-27

**Docs: bring the README "Influences & what we adopted" table current.** The table had drifted —
it stopped at `0.13.0` while the kit shipped ~13 more external-source adoptions. Since the README is
the package's PyPI long-description, this republishes so the public page reflects the full ledger.

- Added rows for every external-source adoption since `0.13.0`: repowise (`0.11.0`, backfilled),
  OpenSpec (`0.34.0`), gstack + superpowers `systematic-debugging` (`0.35.0`), Karpathy-skills ·
  addyosmani · shanraisshan presentation polish (`0.36.0`), temporalio/skill-temporal-developer
  (`0.37.0`), wdm0006/python-skills (`0.38.0`), the athola/claude-night-market 4-part audit
  (`0.39.0`–`0.42.0`), OpenTelemetry · W3C Trace Context · Grafana Tempo (`0.43.0`), Claude Code docs
  (`0.44.0`), library-skills (`0.45.0`), murphytrueman/design-system-ops (`0.46.0`), the alibaba org
  review (`0.47.0`), and alibaba/open-code-review (`0.48.0`).
- Folded ponytail's second adoption (the pre-code Reuse/YAGNI gate, `0.33.0`) into its existing row.
- Refreshed the "latest three reviews, in a bit more depth" details block (was `0.8`–`0.10`) to the
  actual latest three: design-system-ops, the alibaba org review, and open-code-review.

Docs-only (README is the sole content change); no payload/count/anchor changes. Version 0.48.0 → 0.49.0.

## [0.48.0] — 2026-06-27

**Adopt the partition-for-coverage review methodology from `alibaba/open-code-review`** (Apache-2.0,
re-derived in prose — not vendored). A detailed read of open-code-review showed most of its methodology
(multi-axis dimensions, line-level grounding + re-verify, severity, multi-model review) was already in
the kit; the one genuine gap was **complete file coverage on large changesets**, where AI reviewers
silently skip files. The kit's existing guidance covered *depth allocation* (hotspots) but not
*coverage guarantee*.

- **`skills/code-review-and-quality`** — new "Cover Every Changed File: Partition, Plan, Then Weight
  Depth" section: enumerate changed files deterministically (the diff is the checklist of record),
  bundle related files into one review unit, review each bundle in isolated context concurrently,
  plan-before-deep-pass on big diffs, and reconcile so every file gets a verdict. The existing hotspot
  section is reframed as the *depth* step that follows coverage. New coverage item in the review
  checklist.
- **`agents/sdlc-code-reviewer`** — "Cover Before You Score" note + a Coverage checklist category
  (every changed file accounted for; related files reviewed as bundles).

Coverage = every file accounted for; depth = how hard you looked, allocated next. No count/anchor
changes (skill + agent extended, none added). Version 0.47.0 → 0.48.0.

## [0.47.0] — 2026-06-27

**Adopt 5 verified agentic-engineering patterns from an exhaustive review of the Alibaba GitHub org**
— all 542 repos were reviewed; the overwhelming majority (Java middleware, ML/inference infra, mobile
UI, frontend frameworks) yield nothing transferable to a stack-agnostic config scaffolder, and an
adversarial verification pass dropped a sixth candidate (`p3c`) as unsubstantiated + already covered.
The five that survived are re-derived **in prose (never vendored)** from Apache-2.0 sources, and the
agnostic core stays free of framework/product names:

- **`rules/evals.md` §7 — staged, leak-resistant eval pipelines** (from `alibaba/atrex-bench`):
  sequential gates (build → correct → efficient, each gating the next), generate/grade session
  isolation so the model can't read the answer, and objective external baselines instead of
  self-grading.
- **`rules/agent-guardrails.md` §5 — operation authorization** (from `alibaba/open-agent-auth`): a
  delegated user→agent→operation authority chain, per-request revocable credential scope, a verifiable
  audit trail, and runtime-updatable authz policy — distinct from the existing input/output/tool
  guardrails.
- **`rules/tool-design.md` §8 — orchestrating a tool *set*** (from `alibaba/app-controller` +
  `alibaba/loongsuite-js`): registry-based discovery, plan-before-execute, concurrent independent
  calls, durable cross-turn workflow state, written atomically (tmp-write-then-rename) to survive
  concurrent hooks/agents.
- **`rules/goal-setting-and-monitoring.md` §4 — instrument the run** (from `alibaba/loongsuite-js`):
  model the agent run as a `session → turn → tool/LLM` span tree hung off the host's existing hooks,
  with a stable (GenAI-semconv) attribute vocabulary — measured monitoring, not assumed.
- **`skills/debugging-and-error-recovery` — live-attach debugging** (from `alibaba/arthas`;
  `jvm-sandbox` referenced for concept only): the missing third mode (attach → instrument/profile/
  inject-fault → observe → detach) for non-reproducible production bugs where restart is infeasible,
  gated as a `block`/`confirm`-tier action with multi-language illustrative tooling.

No count/anchor changes (rules and skills extended, none added). Version 0.46.0 → 0.47.0.

## [0.46.0] — 2026-06-27

**New `design-system-ops` collection skill** — the **operations layer** for a design system: the work
*after* components are built. Where the existing `radix-tailwind-component-patterns` / `component-design`
skills *build* components and `ui-ux-design` verifies *one* screen during implementation, this skill
audits, governs, documents, validates, and measures the **system as a whole, over time** — the genuine
gap in the kit's design coverage.

- **`skills/design-system-ops/`** — `SKILL.md` (operations lifecycle: audit → govern → document →
  validate → communicate, with explicit `Do NOT use … → use <sibling>` boundaries) + `README.md` +
  five `references/`:
  - `token-architecture.md` — three-tier token model (primitive → semantic → component),
    strictly-downward references, naming, DTCG 2025.10 alignment, cross-platform handling.
  - `system-health-and-maturity.md` — seven health dimensions, library-type classification, five
    maturity stages, and how to grade/calibrate.
  - `drift-detection.md` — four drift kinds (visual/behavioural/API/token), A/C/E classification,
    styling-specific token-drift detection, severity, trend tracking.
  - `governance-and-adoption.md` — deprecation, decision records, contribution + change communication;
    adoption model (coverage ≠ adoption, four signals, leading/lagging, per-team).
  - `ai-readiness.md` — context cascade, three pillars, six AI-readiness dimensions, Component
    Challenge Rating calibration.
- **Reuse-first, attributed:** frameworks **re-derived stack-agnostic** (not vendored) from the
  MIT-licensed [`murphytrueman/design-system-ops`](https://github.com/murphytrueman/design-system-ops)
  (© 2026 Murphy Trueman), re-expressed in the kit's idiom.
- **Cross-links:** reciprocal scope-boundary pointer added to `ui-ux-design` (per-feature build-time →
  this system-wide layer); decision records route to `documentation-and-adrs`; WCAG to
  `accessibility-review`.
- **Counts:** skills **103 → 104** (collection **47 → 48**, core unchanged at 56); `docs/stack-skills`
  table row + routing entry added.

## [0.45.0] — 2026-06-27

**Adopt `library-skills` as a referenced companion** — [`library-skills`](https://library-skills.io)
(MIT) is a tool (`uvx library-skills` / `npx library-skills`) that installs a dependency's
*author-shipped, version-synced* skills into `.claude/skills/` (via managed symlinks) so an agent uses
a library's **current** API instead of stale training-data patterns. It is the same root defense as
`dependency-verification` (the model's memory of an API is a *claim*, not a fact), one step later in
the dependency lifecycle — so it is wired in **reuse-first** (referenced, never vendored; no new skill,
since it would duplicate the existing Context7 live-docs MCP):

- **`dependency-verification`** gains a *"use its current API"* layer in its supply-chain-lifecycle
  diagram (between install and the post-install CVE audit), naming `library-skills` (for libraries that
  ship skills today) and Context7 (live docs for the rest) as the two ways to ground usage in the
  source rather than the model's memory.
- **`library-review`** notes the post-adopt step (once you adopt, pull the library's current skills/docs)
  and adds a `library-skills` entry to its Related list.
- **`catalog/mcp.yaml`** documents `library-skills` as the no-MCP companion to the Context7 docs server.

No new skills/agents and no count changes; honest about the tool being nascent (it only helps for the
growing set of libraries that ship skills).

## [0.44.0] — 2026-06-27

**Token-economy pass** — cut claude-kit's eager per-session context cost without removing any SDLC
capability. Grounded in the official Claude Code cost/settings/hooks/memory docs and a measured audit
of the kit's own footprint; full state stays on disk, full pipeline detail stays in the on-demand
rules, and **no** model/effort/thinking levers were changed (every gate keeps its current model).

- **SessionStart hooks no longer dump whole files into context.** `hooks/scripts/load-continuity.sh`
  replaced its unbounded `cat CONTINUITY.md` (the single largest eager cost — a mature working-memory
  file ran ~33 KB / ~8,300 tokens **every** session) with a bounded head+tail digest that preserves
  both ends (Current Phase / Active Tasks at the top, Next Steps / Blocked / Test-Build Status at the
  bottom) and trims only the unbounded middle; a 49 KB file now injects ~7.9 KB. Small files are
  emitted unchanged. `load-learnings.sh` gained the same cap on the learnings index. The full files
  stay on disk and are pointed to in the trimmed output.
- **The scaffolded `settings.json` now ships token-budget defaults** (added in `build_settings()`, so
  both the pip-installed file and the no-pip `templates/settings.json` starter carry them, enforced by
  a new parity test): `env.CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1` (skips a background Haiku title call
  in headless/subagent runs), explicit `autoCompactEnabled: true` (the kit's
  CONTINUITY-survives-compaction design depends on it), and `maxSkillDescriptionChars: 1100` (above the
  longest current skill description of ~973 chars, so nothing truncates today while capping the
  per-turn skill-listing as the catalog grows). Deliberately **not** baked in:
  `model`/`fallbackModel`/`effortLevel`/`MAX_THINKING_TOKENS` — those would silently lower reasoning on
  judgment-heavy gates (left for an explicit opt-in profile later).
- **`templates/CLAUDE.md` trimmed 246 → 157 lines** (~3.2 KB off the one file loaded in full every
  session). The pipeline prose that merely restated `mandatory-workflow.md` / `quality-gates.md`
  (already read on-demand by the agents) is collapsed to a tight phase index that defers to those
  rules; every `.claude/rules/*.md` citation is kept, the per-task "Coding Behavior" guidance is kept
  verbatim, and a `## Compact instructions` section was added so auto-compaction preserves the
  resume-critical state. Meets the official sub-200-line CLAUDE.md guideline.

## [0.43.0] — 2026-06-26

**New `otel-tracing` collection skill** — vendor-neutral distributed tracing with OpenTelemetry and
Grafana Tempo. Re-derived from public OpenTelemetry, W3C Trace Context, and Grafana Tempo
documentation; nothing vendored, no proprietary content.

- **`skills/otel-tracing/`** (new collection skill) — the language-neutral tracing **pipeline and
  backend**, complementary to the app-side `observability-and-logging`. `SKILL.md` covers the OTel
  trace data model, the standard OTLP env-var contract (incl. the 4317-gRPC / 4318-HTTP +
  `/v1/traces` port/path traps and the missing-`service.name` trap), the signal pipeline, env-gated /
  fail-safe / idempotent instrumentation (auto + manual + framework, init order, span processors),
  head-plus-tail sampling, Tempo essentials (distributor/ingester/querier/compactor, retention, the
  metrics-generator), and trace↔logs↔metrics correlation. Six references go deep:
  `instrumentation.md`, `collector.md`, `sampling.md`, `tempo.md`, `correlation.md`, and `gotchas.md`.
- **Clean auto-trigger boundaries** — the `description:` routes app-side observability code to
  `observability-and-logging` and LLM/model tracing to `langfuse-llm-tracing`; both siblings carry a
  reciprocal pointer back (the `observability-and-logging` OTel section now points to `otel-tracing`
  for the pipeline/backend layer). The neutral policy stays in `.claude/rules/devops-observability.md`
  and the role stays the `observability-engineer` agent.
- Counts: **102 → 103** total skills (**46 → 47** stack-collection; core unchanged at 56).

## [0.42.0] — 2026-06-26

**Doc hygiene + workflow polish** (PR 4 of 4 — the final adoption from the MIT
`athola/claude-night-market` audit; re-derived stack-agnostic, nothing vendored).

- **`skills/documentation-and-adrs`** gains a **generated-doc quality gate** — run on any doc an agent
  wrote/rewrote before commit. Hard fails: identity/voice leaks ("As a large language model", "Great
  question!", self-narration), **hallucinated references** (every backticked identifier/path/config
  key must exist; every install command must resolve — ties to `dependency-verification`), and
  **unverified quality claims** ("production-ready"/"fast" with no in-repo evidence — the prose form of
  the `code-review-and-quality` grounding rule). Plus human-quality principles: slop is a *density*
  problem not a banned-word list, thesis-first, earn every sentence, prose over bullet waterfalls, drop
  the machine tells. (From `slop-detector`/`doc-generator`.)
- **`skills/doc-consolidation/`** (new core skill) — harvest the ephemeral `*_REPORT.md`/`*_ANALYSIS.md`
  that runs leave behind into canonical docs (ADRs, plans, CHANGELOG, existing docs), then delete the
  sources. Two-phase: read-only triage → **approval gate** → merge → verified delete (deleting files
  you didn't author is confirm-tier, `human-in-the-loop.md`). Routes durable *lessons* to
  `agent-memory/`, not docs. (From `sanctum:doc-consolidation`.)
- **`rules/continuity.md`** gains a **dual-probe summary check** — before any handoff/pre-compaction,
  test the summary with a *progress probe* ("what's done + exact state?") and a *gap probe* ("what's
  still needed?"); a hedged progress answer or an open-ended gap answer means rewrite it now. Catches
  the confident-but-wrong summary the gap probe alone misses. (From `memory-clarity-probe`.)
- **`rules/tool-design.md`** gains **§7 "Spend the resource in proportion to its value"** — Brooks's
  law for agents (more parallel agents ≠ more throughput), source only high-value/changing claims, and
  keep output dense. (Folds the genuinely-additive kernel of the `conserve` skills.)
- **`rules/evals.md`** — the LLM-as-judge grader note now recommends an explicit **weighted rubric**
  for multi-dimensional grading (kept for *grading*; the pass/fail gate stays binary). (Minimal ADAPT
  of `leyline:evaluation-framework`.)
- *Deliberately skipped* (reuse-first, no duplicates): `conserve:decisive-action` (already covered by
  the 0.41.0 `human-in-the-loop` reversibility gate + `agent-guardrails` confirm/allow tiers);
  `evaluation-framework` as a standalone skill (its weighted-scoring kernel folded into `evals.md`
  instead, per the audit critic).
- Counts: **101 → 102** total skills (**55 → 56** core; collection unchanged at 46).

## [0.41.0] — 2026-06-26

**Escalation discipline + safety/shell review lenses** (PR 3 of 4 from the MIT
`athola/claude-night-market` audit; re-derived stack-agnostic).

- **`rules/model-tiers.md`** gains a **"When to escalate a tier"** section: the Iron Law
  (no escalation without investigation first), a 4-question gate (understood? investigated? right lever?
  worth it?), legitimate triggers, and an **anti-rationalization table** that catches "maybe a smarter
  model will figure it out." Ties into the agent-resilience 3-strike rule + quality-gates escalation.
- **`rules/human-in-the-loop.md`** gains a **reversibility gate**: classify a decision as one-way vs
  two-way door across undo-cost/blast-radius/data/externalization/commitment, and scale review
  proportionally (proceed → adversarial pass → stop-and-ask + premortem/watch-points/reversal-plan).
  Also flags *false irreversibility*. (Adapted from war-room's reversibility scoring; the multi-LLM
  panel was dropped — it overlaps the orchestrator/`devils-advocate`.)
- **`skills/safety-critical-patterns/`** (new core skill) — NASA Power-of-10 high-reliability lens
  adapted language-neutral, **gated by "match rigor to consequence"** (full for money/medical/
  data-integrity/auth/irreversible; light for scripts) so it never over-applies to CRUD. Composes with
  `risk-classification`.
- **`skills/shell-review/`** (new core skill) — audits CI/hook/build/wrapper shell for exit-code
  propagation (`set -euo pipefail`, capture-output-and-status), POSIX-vs-bash portability, safety
  (quote/brace vars, `:?` required vars, `cd` in a subshell, `mktemp`+`trap`), and library/executable
  structure; `shellcheck` as the backstop. (Re-derived without the upstream's bespoke logging/guard
  conventions.)
- Counts: **99 → 101** total skills (**53 → 55** core; collection unchanged at 46).

## [0.40.0] — 2026-06-26

**Review grounding + addition scrutiny** (PR 2 of 4 from the MIT `athola/claude-night-market` audit;
re-derived stack-agnostic, count-neutral — both are edits to existing skills).

- **`skills/code-review-and-quality`** — Step 4 now requires every finding to be **grounded**: a
  `file:line` Location + a verbatim Anchor snippet, re-verified before reporting; a finding whose
  location/anchor doesn't resolve is dropped or labelled `UNVERIFIED`. Stops AI reviewers from
  hallucinating locations/issues; the review-level form of the §2.5 evidence rule in `quality-gates.md`.
- **`skills/over-engineering-review`** — new **Burden-of-Proof Scrutiny** section that inverts the
  default for *additions* in diff mode: 5 scrutiny questions (priority/criticality/simplicity/evidence/
  consequence), 6 AI-additive anti-patterns (wheel reinvention, hallucinated issue, test manipulation,
  complexity creep, priority deviation, gold plating), a justified/needs-evidence/unjustified verdict,
  and the subtractive question. Collapses the upstream additive-bias-defense + justify + bloat-detector
  ideas into the kit's existing complexity-review skill.

## [0.39.0] — 2026-06-26

**Supply-chain defense** (first of four adoptions from the MIT [`athola/claude-night-market`](https://github.com/athola/claude-night-market);
re-derived stack-agnostic, nothing vendored). Closes the pre-install gap between "should we add a dep"
(§2a.5 / `library-review`) and "are our installed deps vulnerable" (`dependency-scanner`).

- **`skills/dependency-verification/`** (new core skill) — pre-install verification that a package
  **name** actually exists in its registry (PyPI/npm/crates.io/…) and isn't a typosquat/slopsquat,
  before any install command or manifest edit. Defends against LLM-hallucinated package names
  (~5–22% of model-suggested packages don't exist; the recurring names get pre-registered with
  malware). Three states — exists / nonexistent / unverified — and **never fails closed on a network
  error**. Cross-linked into the supply-chain layer chain (§2a.5 → library-review → this → install →
  dependency-scanner).
- **`agents/dependency-scanner.md`** gains a **Supply-Chain Integrity mode** (post-resolve):
  lockfile/hash integrity, artifact + lifecycle-script scanning, known-bad-versions cross-check, and
  provenance signals — beyond the existing CVE audit.
- **`skills/security-and-hardening`** + **`skills/library-review`** updated to point at the new layers.
- Counts: **98 → 99** total skills (**52 → 53** core; stack-collection unchanged at 46).

## [0.38.0] — 2026-06-26

**New `library-review` core skill + a property-based-testing note** (two genuinely-new ideas
cherry-picked, stack-agnostic, from the MIT [`wdm0006/python-skills`](https://github.com/wdm0006/python-skills);
the rest of that collection was skipped as redundant with existing core/collection skills).

- **`skills/library-review/`** (core — SKILL.md only, stack-agnostic) — a structured **pre-add
  dependency-adoption evaluation**: need & fit, alternatives (stdlib/native/existing dep),
  maintenance & bus factor, license compatibility, security/supply-chain history, transitive weight,
  lock-in/exit cost, and a documented adopt/reject decision. Re-cast (health-signal dimensions
  adapted from the MIT upstream's `reviewing-python-libraries`) as an *adoption* gate. Reuse-first:
  cross-linked to and explicitly bounded against `mandatory-workflow.md` §2a.5 (whether a dep is
  needed at all), `over-engineering-review`, the `dependency-scanner` agent (audits *installed* deps —
  this is its pre-add counterpart), and `code-review-and-quality` (whose 5-point Dependency
  Discipline list now points here as its full form).
- **`test-driven-development`** gains a **Property-Based Testing** section (count-neutral edit):
  what it is, when to reach for it, the round-trip/idempotence/invariant/metamorphic property shapes,
  and one-per-language ecosystem pointers (Hypothesis · fast-check · jqwik · proptest · …).
- Counts: **97 → 98** total skills (**51 → 52** core; stack-collection unchanged at 46). No
  `docs/stack-skills` row (core skills aren't listed there). Version bumped across the 5 parity files.

## [0.37.0] — 2026-06-26

**New `temporal-developer` collection skill — Temporal *fundamentals*, language-agnostic** (re-derived
concisely from the official MIT [`temporalio/skill-temporal-developer`](https://github.com/temporalio/skill-temporal-developer);
nothing vendored, cross-checked against https://docs.temporal.io). Complements — does **not** duplicate —
the existing `temporal-config-driven` skill (which stays scoped to this kit's config-driven worker-map /
DAG-as-data architecture and *assumes* these fundamentals).

- **`skills/temporal-developer/`** (SKILL.md + README.md with MIT provenance) covers the durable-execution
  model, **why workflows must be deterministic** (history replay → Command/Event matching), the
  workflow/activity/worker split, Query vs Signal vs Update, and six compact references:
  `determinism.md`, `versioning.md` (patching · workflow-type · worker/Build-ID versioning),
  `testing.md` (local/time-skipping env, activity mocking, replay tests), `gotchas.md`,
  `cli.md` (`temporal server start-dev` + the `workflow start/execute/signal/query/update` dev loop),
  and `languages.md` (Python/Go/TypeScript starters + pointer to upstream Java/.NET/Ruby/Rust depth).
- **Auto-trigger boundary** wired both ways: each skill's `description` carries an explicit
  `Do NOT use … → use <sibling>` clause, with reciprocal pointers in both SKILL.md/README.md bodies.
- Counts: **96 → 97** total skills (**45 → 46** stack-collection; core unchanged at 51), plus a new
  `docs/stack-skills` catalog row. No catalog/stack/hook/agent changes (Temporal is a skill, not a stack axis).

## [0.36.0] — 2026-06-25

**Rule-presentation + context-hygiene polish** (patterns adopted from Karpathy-skills, addyosmani/agent-skills,
and shanraisshan/claude-code-best-practice — all MIT; presentation only, no substance change). Same rules,
stickier and more actionable:

- **6 high-value rules** (`mandatory-workflow`, `quality-gates`, `agent-resilience`,
  `goal-setting-and-monitoring`, `reasoning-techniques`, `code-organization`) each gain a **bold quotable
  tagline** under the H1, one or two **embedded self-check** lines in their key section, and a measurable
  **"This rule is working if …"** success-signal line.
- **`skills/context-engineering/SKILL.md`** gains quantitative guardrails: a **<200-line CLAUDE.md target**,
  a **degradation-zone threshold** (~40% of window) in the failure taxonomy, **session-boundary heuristics**
  ("new task = new session"; summarize-before-rewind) under Level 5, and a **≈30% baseline headroom** target
  for progressive disclosure.

Markdown-only, count-neutral (no new rules/skills); existing behavior unchanged.

## [0.35.0] — 2026-06-25

**3-strike fix-attempt discipline** (pattern adopted from gstack's "Iron Law" + the superpowers
`systematic-debugging` skill, both MIT; re-derived in claude-kit's idiom). Retry *budgets* existed for
gates and operations, but nothing bounded blind *fix* attempts on a single bug:

- **`rules/agent-resilience.md` — new "Fix-attempt discipline (the 3-strike rule)" section.** Attempts
  1–2 must each test a *different, explicit* hypothesis (a near-duplicate edit doesn't count). At the
  3rd failed attempt: STOP — re-derive the root cause (`debugging-and-error-recovery` skill), question
  whether the *approach/architecture* is wrong (not the line), then escalate via `human-in-the-loop.md`
  with what each attempt ruled out. Explicitly scoped against the `quality-gates.md` defect-loop budget
  (that bounds review→fix cycles across the pipeline; this bounds blind attempts within one issue).

Single-rule, count-neutral change; existing commands unaffected.

## [0.34.0] — 2026-06-25

**Delta-specs + change-scoped artifacts** (pattern adopted from [OpenSpec](https://github.com/Fission-AI/OpenSpec),
MIT; re-derived in claude-kit's idiom). The spec flow was greenfield-only — every change wrote a full
spec. This adds an incremental path for brownfield work, mirroring how `api-change-report.md` already
complements `feature-spec.md` for API contracts:

- **New `templates/artifacts/change-proposal.md`** — a delta spec keyed to the base spec's stable
  `R#` ids, with `ADDED` (new requirement + Given/When/Then) / `MODIFIED` (`was: … → now: …` + acceptance
  delta) / `REMOVED` (reason + migration) sections, change-scoped scope, a backward-compat/migration
  section, and a delta test plan. Auto-installs into `.claude/templates/` (no scaffold change).
- **`skills/spec-driven-development/SKILL.md`** — adds a "Full spec vs delta spec" decision (new system →
  full `feature-spec.md`; change to an already-specced system → delta `change-proposal.md`), a
  "Keeping the Spec Alive" pointer, and an incremental-change clause in the `description:` frontmatter.
  Delta criteria still feed the stage-1f coverage gate.
- **`templates/artifacts/feature-spec.md`** — preamble now points incremental changes at the delta template.

New test asserts the template ships with delta notation. No count changes (templates aren't counted).

## [0.33.0] — 2026-06-25

**Pre-code Reuse & YAGNI gate** (pattern adopted from the [ponytail](https://github.com/DietrichGebert/ponytail)
plugin, MIT; re-derived in claude-kit's idiom, no vendored code). The kit's complexity controls were all
*reactive* (the `over-engineering-review` skill scans bloat out after code exists). This adds the proactive
twin:

- **`rules/mandatory-workflow.md` §2a.5 — Reuse & YAGNI Gate** — a new Phase-2 stage between "read code"
  (2a) and "write code" (2b). Before adding any new file/function/abstraction, the developer walks a
  stop-at-first-rung ladder — *needs to exist? → already in the codebase? → stdlib? → native platform
  feature? → existing dependency? → minimum that works?* — applying the same delete/stdlib/native/yagni/
  shrink lenses as `over-engineering-review`, but *before* the code is written. Wired into the Quick
  Reference flow and the pipeline-gating table.
- **`skills/over-engineering-review/SKILL.md`** — cross-links the gate as its proactive twin.

No catalog/hook/agent/count changes; existing commands unaffected.

## [0.32.0] — 2026-06-25

**Two patterns adopted from Agent-Reach (MIT); no behavior change to existing commands.**

- **`claude-kit init --dry-run`** — preview the resolved plan (stack / profile / scope / MCP / gates)
  and the exact list of files a fresh install would write, **without touching the target project**.
  Implemented by running the real installer into a throwaway sandbox and discarding it, so the preview
  can never drift from a real install. Great for CI, onboarding, and evaluation.
- **Root `llms.txt`** — a concise, machine-readable project guide (the llmstxt.org convention) so agents
  and tools discovering the repo get install + key-command + concept pointers fast. Repo artifact only;
  not shipped in the wheel/sdist or scaffolded into projects.

## [0.31.0] — 2026-06-24

**Sharper skill auto-triggering.** Added explicit `Do NOT use when … → use [sibling]` boundary clauses to
the `description:` frontmatter of the most overlapping **model-invocable** skills, so the model routes to
the right skill instead of coin-flipping between siblings whose "Use when" clauses both match a request:

- **`*-driven-development`** — `test-driven-development`, `spec-driven-development`,
  `source-driven-development`, `doubt-driven-development` now cross-route (spec before code exists, source
  for "which API is correct", TDD for the red-green loop, doubt as the review layer *on top* of the others).
- **Security** — `security-and-hardening`, `threat-model`, `zap-vapt-scanning`,
  `kubernetes-workload-hardening`, `edge-to-service-trust-boundary` now disambiguate code-hardening vs
  upfront STRIDE vs live DAST scan vs k8s-manifest/pod hardening vs the gateway signed-header trust contract.
- **Testing** — `testing-conventions` routes the red-green loop to `test-driven-development` and pre-write
  plan critique to `test-plan-review`.

Skills carrying `disable-model-invocation: true` (slash-only; they never auto-trigger) were intentionally
left untouched. The clauses were adversarially verified for truthful routing, coverage, and the ~1024-char
description ceiling. Skill-`description` text only — no agent, rule, hook, catalog, or pipeline behavior change.

## [0.30.0] — 2026-06-24

**The flagship example is now a *real, harness-captured* `/sdlc` run — closing the credibility gap that
the prior flagship was synthetic. Plus a harness improvement found by running it. Docs/example +
`capture-sdlc-run.sh` only; no payload or pipeline behavior change.**

### Added
- **`examples/real-run/`** — a genuine run, produced by the kit's own
  [`scripts/capture-sdlc-run.sh`](scripts/capture-sdlc-run.sh) harness. A real `DELETE /tasks/{id}`
  feature was driven through every standard-profile gate on a freshly-scaffolded **Go / net-http**
  project; the folder holds the **verbatim harness bundle** (`captured-bundle/`: the spec, the
  deterministic `pipeline-snapshot.json` with per-gate evidence, the `stack-catalog.snapshot.yaml`, the
  `continuity.md` verdict log, the gate evidence, and the real `git/changes.diff`), the agent verdicts
  the harness's gate model doesn't collect (`run-artifacts/`), the reproducible Go source
  (`sample-app/`, 7 tests / 85.2% coverage), and a **genuine terminal recording** of the gate checks
  (`cast/`: an asciicast `.cast` + static `.svg`, recorded via a stdlib `pty` recorder).
- **The headline:** four reviewers returned a unanimous PASS; the `devils-advocate` (spawned *because*
  of the unanimity) attacked the id-parsing seam over a raw socket and found + **reproduced** a real
  **Medium** — `strconv.Atoi` aliased `01`/`+1`/`%2B1` onto task `1` and deleted it. The deterministic
  pipeline then **refused to close the next gate** while the Medium was open; a fix + a mux-level
  regression test closed it and the devil's advocate re-verified **UPHELD**.

### Changed
- **`scripts/capture-sdlc-run.sh` now produces a self-contained bundle** (improvement surfaced by
  actually running it): it copies the gate-evidence files the snapshot references into the bundle's
  `evidence/` and rewrites the snapshot's `gate_evidence` paths to bundle-relative, so a published
  bundle resolves its own pointers and leaks no local absolute filesystem paths. Degrades gracefully
  (with a note) when `python3` is absent.
- **The README and `examples/` index now lead with the real captured run**; the
  `react-fastapi-postgres-feature/` walkthrough is reframed as the explicitly *synthetic* map alongside
  it, and `docs/capture-a-real-run.md` points at the shipped real bundle as a worked reference.

## [0.29.0] — 2026-06-24

**Positioning v2 (docs): lead with the trust moat, promote the comparison to a top-level block, and
add a 60-second first-win path. No behavior change.**

### Changed
- **The hero now leads with the moat, not orchestration.** The tagline is *"the autonomous SDLC for
  Claude Code that won't pass a gate on an unproven verdict"* — orchestration is table stakes; the
  evidence requirement is the differentiator, so it's the first thing you read.
- **"How claude-kit compares" is now a prominent top-level section** (was a collapsed block buried
  under *Influences*), leading with **Native Claude Code subagents / Agent Teams** — the alternative
  every user weighs first. Honest framing throughout: native gives you the agents, claude-kit adds the
  governance.

### Added
- **"60-second first win" section.** A three-line fast path — `/plugin install` →
  `/claude-kit:sdlc <task>` — with **no CLI install, no `init`, no restart**: the plugin loads the
  Orchestrator + agents on install, and the `sdlc` skill/command fall back to the standard pipeline
  when project config is absent. `init` is reframed as the *tune-it-to-your-repo* step (exact commands,
  hooks, upgrade tracking), not a prerequisite to the first run.

## [0.28.0] — 2026-06-24

**Positioning & onboarding pass (docs): surface the anti-fabrication moat, compare against native
subagents, and ship a real-run capture harness. No behavior change.**

### Added
- **`scripts/capture-sdlc-run.sh` + [`docs/capture-a-real-run.md`](docs/capture-a-real-run.md).** A
  read-only helper that bundles one completed `/sdlc` run — the spec (`docs/specs/`), the gitignored
  gate state (`.claude/state/pipeline-snapshot.json`), the verdict log (`.claude/CONTINUITY.md`), and
  the diff vs your base branch — into one publishable folder. It runs a generic secret scan (lists
  matching **file names only**, never values) and writes a manual `REDACTION-CHECKLIST.md`, so a real
  run can become a worked example without hand-collecting files.
- **"Native Claude Code subagents / Agent Teams" comparison row** in the README — the alternative
  every Claude Code user weighs first. Honest framing: native gives you the agents; claude-kit adds
  the *governance* (sequenced pipeline, owned gates, evidence requirement, `devils-advocate`, resume).

### Changed
- **The anti-fabrication evidence requirement is now the headline trust idea.** "How it works" leads
  with *"Evidence or it didn't happen"* — every gate verdict must cite the command + captured output
  (or `file:line`), and an invented/assumed/partial-output verdict is an auto-Critical finding
  (`rules/quality-gates.md` §2.5). The top-of-README tagline now states gates pass only on real,
  cited output. (The rule itself is unchanged; it was previously only implied via RARV.)

## [0.27.0] — 2026-06-24

**Objective fixes from a product review: honest skill counts (with a guard), drift-aware
`doctor`/`validate`, and a distinct corrupt-vs-missing manifest signal.**

### Added
- **`validate`/`doctor` now surface kit-owned drift.** They already verified that every tracked file
  is *present*; they now also compare each kit/overlay file's live SHA-256 against the install
  manifest and emit `N kit-owned file(s) modified since install … run claude-kit diff` (a WARN, never
  a FAIL — edits to user-editable files are not flagged). The manifest data already existed; only
  `diff`/`upgrade` consulted it before.

### Changed
- **Honest skill counts.** The README advertised "51 skills" — the count of *core* skills only, while
  the repo ships **96** (51 stack-agnostic core + 45 stack-collection). All three occurrences now read
  "96 … (51 core + 45 stack-collection)", and `check_docs_consistency.py` pins the headline total
  **and** both halves to the filesystem so the number can't silently drift again.
- **Corrupt vs missing `init-options.json` are now distinct signals.** A missing manifest stays a WARN
  ("validate/upgrade limited"); a *corrupt* one is a FAIL ("unreadable … repair the JSON or re-run
  `claude-kit init --force`") in `validate`, `doctor`, `diff`, and `upgrade` — matching how the kit
  already reports a malformed `settings.json`/`.mcp.json`.

## [0.26.1] — 2026-06-24

**A second strict practical review (installed and exercised end-to-end) surfaced seven papercuts on
top of 0.26.0 — all bug fixes and polish, no behavior change for existing configs.**

### Changed
- **The destructive-delete guard is no longer order-dependent.** The previous regex only matched
  `r…f` order, so `rm -fr`, `rm -r -f`, `rm -Rf`, and `rm --recursive --force` slipped through. It now
  blocks any invocation that combines a recursive flag **and** a force flag in any order or spelling
  (incl. `-R` and long flags); the plugin `hooks.json` and starter `settings.json` were regenerated
  from the registry. New functional tests fire JSON payloads through the guard to lock the behavior in.
- **CI lints shipped skill Python** (`ruff check … skills`), so future skill scripts are covered;
  `zap_vapt.py` import ordering was fixed to match.

### Fixed
- **Upgrade artifacts are now gitignored.** `claude-kit upgrade` writes `.claude-kit.bak-*/` backup
  dirs and `*.claude-kit` sidecars; a scaffolded `.gitignore` now lists both so `git add -A` never
  commits a backup.
- **Frontmatter hygiene, swept across every component.** Two skill descriptions over the 1024-char cap
  (`design-patterns-and-conventions`, `shannon-ai-pentest`) were trimmed; `security-reviewer` and two
  `templates/org` skills (`prompt-to-safe-task`, `repo-onboarding`) had unquoted `: ` scalars that
  fail strict YAML and are now quoted; `smoke-test`'s `argument-hint` is a valid YAML string. A new
  `tests/test_frontmatter.py` parses every shipped agent/command/skill under strict YAML and enforces
  the description cap, so these regress loudly.

## [0.26.0] — 2026-06-24

**Post-hardening follow-up: two correctness/security fixes plus polish, all from a verified review
punch list.**

### Added
- **Plugin now guards secret-file reads out of the box.** `protect-secrets` (PreToolUse/Read — blocks
  reading `.env`/`.pem`/`.key`/`id_rsa`/credentials/…) was installed by the pip CLI (it's in the
  `standard`/`all` profiles) but missing from the always-on plugin hook set, so plugin-only users had
  no Read guard until they ran an init. It's now in `PLUGIN_HOOK_IDS`; `hooks/hooks.json` gains a
  `PreToolUse`/`Read` group.
- **`.github/dependabot.yml`** for the `github-actions` ecosystem (weekly, grouped) so CI/publish
  actions are kept current and SHA-pinned by Dependabot's PRs, with auditable tag comments.
  `pypa/gh-action-pypi-publish` stays on `release/v1` (required for Trusted Publishing + attestations).

### Changed
- **`pipeline close-gate` enforces the blocking-findings rule.** It now refuses to record a gate as
  passed while any **critical/high/medium** findings are open (`rules/quality-gates.md`); low/cosmetic
  still pass. A deliberate override requires `--force` **with** `--override-reason "<why>"`, recorded
  under `gate_overrides[gate]` for human review.
- **`pipeline validate` re-checks gate evidence.** When a gate is recorded passed and has a
  `gate_evidence` path, validate now fails if that file no longer exists on disk, and surfaces any
  force-closed gate. Lenient on the upgrade path (no evidence map → silent; partial map → warn).
- **Inline hook guards quiet their `jq` calls** (`2>/dev/null || true`) so malformed/missing hook JSON
  can't spam stderr — matching the script-backed guards; `guard-secrets.sh` aligned for consistency.

### Fixed
- **Docs consistency checker catches duplicate gate tables.** `check_docs_consistency.py` previously
  keyed profile gate rows in a dict, so a second (possibly stale) table could silently overwrite an
  earlier one; it now collects every occurrence, flags duplicates, and requires each to match
  `profiles.yaml`.
- **Stale comments in `scripts/init.sh`** corrected: it's described as the degraded, no-resolution
  fallback (the pip CLI is the catalog-driven/upgrade-safe installer), and existing files are noted as
  written to `*.claude-kit` sidecars (not `*.example`).

## [0.25.0] — 2026-06-24

**PR4 of the phased hardening review: supply-chain provenance, an explicit trust model, and a full
genericization pass so the public repo carries only neutral examples.**

### Added
- **PEP 740 build attestations re-enabled** in `publish.yml`. They were temporarily disabled while
  Sigstore's Rekor transparency log was returning HTTP 502s at upload time; Sigstore has since been
  healthy (verified via status.sigstore.dev — all services online, no incidents), so releases are
  signed again for supply-chain provenance.
- **A "Security & trust model" section** in `README.md` (with a nav link) stating plainly that the
  guard hooks are convenience, not a hardened boundary; that most quality gates are agent protocols
  rather than mechanical enforcement; and that MCP servers are third-party code — surfacing
  `SECURITY.md`'s posture where users decide to rely on the kit.

### Changed
- **Genericization pass** — removed residual internal / company-specific identifiers so the published
  repo carries only neutral examples. Genericized the 0.15.0 adoption narrative in `CHANGELOG.md` and
  `docs/coverage-audit.md`; renamed test functions and replaced an internal-token blocklist with a
  positive neutralization check in `tests/test_scaffold.py`; and neutralized the skills-collection
  reference docs (example feature / module / variable names, domain-specific jargon, and a
  region-specific registry host) into generic equivalents. Examples-only — no behavior change.

## [0.24.0] — 2026-06-24

**PR3 of the phased hardening review: deeper validation, a deterministic pipeline CLI, an MCP
lockfile, and a CI matrix that brings every distribution channel and quality dimension under test.**

### Added

- **`claude-kit validate --strict`** — beyond the structural checks, strict mode verifies that every
  `settings.json` hook fires on a known event and runs an **installed, executable** script; that
  `.mcp.json` has a sane `{mcpServers: {id: {command|url}}}` shape; that the resolved
  `stack-catalog.snapshot.yaml` agrees with the agents/skills/overlays actually on disk; and that the
  **bundled catalog is referentially consistent** (`validator.check_catalog`: every profile resolves to
  existing agents/skills/registered hooks, every stack overlay rule/agent file is present, and the org
  overlay's new skills/agents/rules/packs exist). `doctor` now runs the strict validate by default.
- **`claude-kit pipeline` command group** (`src/claude_kit/pipeline.py`) — deterministic,
  **non-executing** operations on the `/sdlc` state files: `pipeline validate` (snapshot shape +
  profile/scope/mode/lane/findings coherence, with `last_gate_passed` checked against the installed
  gate set), `pipeline status` (human-readable run summary), `pipeline close-gate <gate> --evidence
  <file>` (records a passed gate, requiring the evidence artifact and a gate name the profile defines),
  and `pipeline abort`. These validate/mutate `.claude/state/pipeline-snapshot.json` — they do **not**
  run the pipeline.
- **`.mcp.lock.json`** — when `.mcp.json` is written, a deterministic lockfile captures the resolved
  package + pinned version (parsed from the `npx -y <pkg>@<ver>` args) or hosted URL per server, so a
  reviewer can see exactly what would run. It is a kit-owned, derived artifact (refreshed on upgrade,
  never a user sidecar). **`claude-kit doctor --mcp`** checks each server's command is on PATH, warns on
  unset `${ENV}` vars, and flags a lockfile that has drifted from `.mcp.json` (warnings only).
- **Expanded CI** (`.github/workflows/ci.yml`) — new jobs alongside the test matrix: `lint`
  (`ruff check` + `ruff format --check` + `mypy`), `shell` (`shellcheck -S warning` over all hook + repo
  scripts), `static` (`gen_hooks.py --check`, the docs-consistency guard, catalog referential
  integrity, and JSON validity of the plugin manifests + `hooks.json`), and `wheel-smoke` (build → install
  into a clean venv → `init --defaults` → `validate --strict` → `doctor`). `ruff`/`mypy`/`shellcheck-py`
  are added to the `dev` extra, with conservative `[tool.ruff.lint]` (no E501) and `[tool.mypy]` config.

### Fixed

- **Latent type/lint bugs surfaced by the new CI** — `upgrader.py` used `ResolvedPlan` in annotations
  without importing it (harmless under `from __future__ import annotations`, but undefined) and passed
  `str | Path` to a `Path`-typed `_compare`; `_format_preview` could dereference `None`;
  `prompts._choose_many` and `__main__` used None-returning calls in value position. All fixed; the
  codebase is now `ruff` + `mypy --ignore-missing-imports` clean. Two hook scripts had redundant,
  shellcheck-flagged glob alternatives (`*__tests__*` under `*test*`; `*oauth*`/`*authoriz*` under
  `*auth*`) — removed with no behavior change.

## [0.23.0] — 2026-06-23

**PR2 of the phased hardening review: structural single-source-of-truth for hooks, and plugin/CLI
parity that fails loud instead of silently degrading.**

### Changed

- **Hooks are now generated from one registry.** The two previously hand-maintained static hook files —
  the plugin's `hooks/hooks.json` and the no-pip starter `templates/settings.json` — are now generated
  from `src/claude_kit/hooks.py` (`HOOK_REGISTRY` + per-channel membership data) via
  `scripts/gen_hooks.py`. They had already drifted (the starter was missing `load-autonomy`, the PR1
  `jq`-degradation prefix, and used a slightly different block message). A drift test
  (`gen_hooks.py --check`, run in the suite) fails the build if either file is hand-edited.
  - The installed per-profile `.claude/settings.json` (built by `build_settings`) is **byte-identical**
    to before — pure refactor, verified against `origin/main`.
  - `hooks/hooks.json` is **semantically identical** to before (reflowed to canonical 2-space JSON; no
    hook added, removed, or reordered).
  - `templates/settings.json` changes only by refreshing its two inline Bash guards to the registry
    versions (gaining the `command -v jq … || exit 0` no-jq degradation + aligned message); same hook
    membership.
- **`guard-kubectl-delete` is now declared data.** It moves into a `PLUGIN_ONLY_HOOKS` map (with a
  `reason`) — the single documented exception to "the registry is the source of truth" — instead of
  being a silent hand-edit in `hooks.json`.

### Fixed

- **Plugin/CLI parity: `/claude-kit:init` requires the CLI and fails loud.** The command no longer
  silently falls back to the thin `scripts/init.sh` scaffolder when neither `claude-kit` nor `ckit` is
  on PATH — it stops and instructs `pipx install claude-code-kit` (or `pip install …`). The shell
  fallback is now opt-in only (`CLAUDE_KIT_BASIC=1`) and prints a loud "degraded, no-resolution
  install; upgrade/diff won't work" warning. README onboarding documents the CLI requirement.

## [0.22.0] — 2026-06-23

**Critical-correctness hardening (PR1 of a phased review): a non-destructive `init` merge that no longer
deletes your files, a CI guard against doc/version/count drift, stricter config validation, pinned
third-party MCP versions, and several P2 fixes.**

### Fixed

- **Data-loss bug in `init` merge mode.** Re-running `claude-kit init` over an existing `.claude/`
  (the default `merge` mode) used to `shutil.rmtree` whole kit-managed directories (`rules/`,
  `skills/<name>/`, `skills/_references/`), silently deleting any file you had added under them.
  `init` now reconciles non-destructively via the new `upgrader.merge_install`, which reuses the
  owner-aware upgrade logic: kit/overlay files are refreshed (user-modified ones backed up to
  `.claude-kit.bak-N/` first), user-editable files are sidecar'd, kit/overlay orphans are pruned, and
  **files the kit doesn't track are never touched**. An untracked hand-rolled `.claude/` is migrated
  safely too (collisions are backed up). `--force` / `overwrite` remains the only destructive path.
- **`README.claude-sdlc.md` is now user-editable.** `init` no longer hard-overwrites it; it honours
  `--force` and otherwise writes a `.claude-kit` sidecar, and `upgrade` protects it like `CLAUDE.md`.
- **Documentation/version drift.** `SECURITY.md` supported-version, the `/sdlc` skill's `standard`
  gate row (added `contract-clear`), and the README hook count (16 → 17) corrected.

### Added

- **`scripts/check_docs_consistency.py`** — a fail-loud guard (run in tests + CI) that re-derives the
  facts and asserts the docs agree: version parity across `pyproject.toml`, `__init__.py`, both plugin
  manifests, the latest `CHANGELOG` heading and `SECURITY.md`; component counts (agents / rules / core
  & collection skills / hook scripts / MCP servers) against every number the docs quote; and the
  profile→gate tables in `README.md` + `skills/sdlc/SKILL.md` against `catalog/profiles.yaml`.
- **Stricter `--config` / selection validation.** A bare `mcp: github` (or `teams: …`) string is
  normalised to a one-element list instead of being iterated character-by-character; malformed shapes,
  unknown config keys, an unknown `frontend_language` for the chosen framework, and an unknown `scope`
  now fail loudly with a clear message (`Selection.from_dict(strict=True)` + `catalog.resolve` checks).

### Changed

- **Pinned MCP server package versions.** `catalog/mcp.yaml` replaces moving `@latest` / implicit-latest
  `npx` tags with exact version pins (snapshot 2026-06-23) for reproducible, supply-chain-aware installs;
  the deprecated official GitHub/Postgres reference servers are flagged. README notes that MCP servers
  are third-party code.
- **Planned CLI commands exit non-zero.** `package-org-pack`, `install-org-pack`, and
  `research import-sources` now exit `2` (still announcing "planned") instead of a silent success-`0`.
- **Inline guard hooks degrade without `jq`.** The `rm -rf` / push-to-main / secrets inline guards (in
  both the plugin `hooks.json` and the CLI registry) now no-op when `jq` is absent, matching the
  script-backed guards and the SECURITY.md promise.

## [0.21.0] — 2026-06-22

**Add two stack-collection skills — `cron-and-scheduled-jobs` (scheduled/recurring jobs across Kubernetes
CronJobs and Temporal Schedules) and `kubectl-operations` (the full kubectl command surface for operating
those workloads) — now 45 skills.**

### Added

- **`cron-and-scheduled-jobs`** — a stack-derived skill documenting how scheduled/recurring jobs are
  configured in system config and invoked, across the two mechanisms this stack uses:
  - **Kubernetes CronJob route** — the schedule is declared in Helm `values.yaml` under a `Crons.<job>`
    block (`Schedule`, `Envs: {MODE: cron, CRON_JOB: <name>}`, `ConcurrencyPolicy: Forbid`, `Suspend`,
    `TtlSecondsAfterFinished`); the chart renders one `batch/v1` CronJob per entry (`restartPolicy:
    Never`, history limits 3/1). The shared image boots one-shot in `MODE=cron` and dispatches a single
    named job from a Python cron registry (simple `name→callable` or rich `name→{task, description,
    schedule}`), instrumented via `record_cron_job_executed`. Documents the chart's missing
    `timeZone`/`startingDeadlineSeconds` and how to compensate.
  - **Temporal Schedule route** — `cron_expressions` vs `ScheduleIntervalSpec` (interval+offset to dodge
    the UTC-cron timezone foot-gun), `ScheduleOverlapPolicy.SKIP` + `pause_on_failure`, and the one-shot
    k8s `Job` (not a CronJob) that registers the schedule. Cross-links `temporal-config-driven` (which
    owns workflow/activity/worker mechanics and the create-or-update registration loop) rather than
    duplicating it.
  - Plus a decision matrix for choosing k8s CronJob vs Temporal Schedule, and the cross-cutting concerns
    (concurrency, timezone, history, missed runs, suspend vs pause, observability, idempotency).
  - Fully genericized; **not** wired into the catalog/scaffold (`claude-kit init` output is unchanged).

- **`kubectl-operations`** — a stack-derived, operations-first skill for running `kubectl` against this
  stack's workloads:
  - **Full command surface**, grouped by task — `get`/`describe`/`explain`/`api-resources`;
    `apply`/`create`/`edit`/`patch`/`set`/`replace`; `logs`/`exec`/`port-forward`/`cp`/`debug`/
    `attach`/`proxy`; `rollout`/`scale`/`autoscale`; `events`/`top`; `label`/`annotate`; `config`
    (contexts & namespaces); `auth can-i`; `wait`/`diff`/`kustomize`; node `cordon`/`drain`/`taint`.
    (`kubectl delete` is intentionally omitted — see the guardrail below — in favour of reversible
    alternatives: `scale --replicas=0`, `rollout undo`, or removing the object from the Git/Helm source.)
  - **Output formatting & selectors** — `-o wide/yaml/json/name/jsonpath/custom-columns/go-template`,
    `--sort-by`, label (`-l`) and field selectors, `--watch`, with copy-ready JSONPath recipes.
  - **Context/namespace/RBAC safety** (the #1 footgun) and **day-2 debugging playbooks** —
    CrashLoopBackOff, ImagePullBackOff, Pending/unschedulable, OOMKilled, a cron that didn't fire, a
    Service with no endpoints.
  - Cross-links `cron-and-scheduled-jobs`, `kubernetes-workload-hardening`,
    `containerization-and-deployment`, `temporal-config-driven`, and `observability-and-logging`. Fully
    genericized; **not** wired into the catalog/scaffold. The collection index is updated (45 skills).

- **Plugin guardrail `guard-kubectl-delete`** — a `PreToolUse(Bash)` hook that blocks `kubectl delete`
  from the agent's Bash tool (exit 2), joining the `rm -rf` / `push main` / `guard-destructive-git` /
  `guard-secrets` destructive-command family. It matches the `delete` **subcommand** as a whole word —
  sparing the safe look-alikes `config delete-context`, `drain --delete-emptydir-data`,
  `wait --for=delete`, and the read-only `auth can-i delete …` — and splits compound commands on
  `;`/`|`/`&` so a chained `… | xargs kubectl delete` can't slip past. It refuses with the reversible
  alternatives (`scale --replicas=0`, `rollout undo`, GitOps reconcile) and degrades to a no-op without
  `jq`. Wired into the **plugin** (`hooks/hooks.json`) only; intentionally **not** added to the pip-CLI
  scaffold registry, so `claude-kit init` output is unchanged.

## [0.20.0] — 2026-06-20

**Expand the stack-specific skill collection: 21 new skills + 7 fold-in enhancements + a security pass,
plus a BigQuery skill extend/trim (now 43 skills).**

### Added

21 new skills under `skills/`. Twenty are genericized engineering skills surfaced by cross-repo gap
analysis (one from a live production Grafana, one bundling an internal OWASP ZAP VAPT tool, and two
security-architecture skills from a cross-repo security gap analysis), grounded in real production
Python/FastAPI, Node/Express, and React services; the twenty-first (`shannon-ai-pentest`) is
documentation for an external third-party tool (see Security):

- **Backend & infra** — `configargparse-yaml-env-layering` (3-layer YAML→configargparse→Pydantic config),
  `redis-caching-patterns` (multi-tenant namespacing, TTL, graceful degradation, SCAN invalidation),
  `gcs-file-storage-patterns` (uploads, signed URLs via impersonation, read CSV/Excel),
  `file-export-and-reporting` (Excel/CSV generation + StreamingResponse downloads),
  `api-pagination-filtering-sorting` (query conventions + response metadata),
  `gcp-cloud-run-github-actions` (Cloud Run deploy via GitHub Actions),
  `notifications-and-messaging` (multi-provider email/SMS with fallback).
- **AI/LLM** — `anthropic-vertex-integration` (Claude on Vertex AI via AnthropicVertex SDK),
  `langfuse-llm-tracing` (LLM tracing, Python + TypeScript).
- **Node/Express** — `node-express-service` (app factory, MODE dispatch, convict, middleware),
  `node-objection-knex` (Objection + Knex data layer + Joi validation).
- **Frontend** — `zustand-state-patterns`, `tanstack-react-query-patterns`,
  `react-hook-form-zod-patterns`, `radix-tailwind-component-patterns`, `vitest-rtl-msw-patterns`.
- **Observability** — `grafana-dashboards-and-alerts` (Grafana dashboard JSON model, `$datasource` +
  cascading `label_values` template variables, RED-metric PromQL across NGINX ingress / OTel
  span-metrics / pod utilization, multi-stage unified-alert rules with label-based routing
  (slack_0/pagerduty_0/webhook_0) + dashboard/panel deep-link annotations, Tempo service graphs, and
  dashboards-as-code provisioning). Grounded in a live production multi-cluster Grafana (~137
  dashboards, 150 alert rules; Prometheus/Tempo/Pyroscope/managed-cloud datasources) and fully
  genericized — pairs with `observability-and-logging` (which emits the metrics these dashboards plot).
- **Security** — `zap-vapt-scanning` (a complete, self-contained OWASP ZAP **VAPT/DAST** setup: the
  bundled single-file `zap_vapt.py` launches ZAP headless, replays endpoints from curl / simple lines /
  a Postman collection, runs passive (and gated active) scans, joins alerts to the most-specific
  endpoint, and renders a branded PDF VAPT report. All report identity — company, location, logo, and
  the Created By / Approved By sign-off names — is supplied at run time via CLI flags or prompts;
  nothing is hardcoded, and the `ReportMeta` defaults ship blank. `--selftest` runs 18 logic checks
  with no ZAP required. Genericized from an internal tool — passive default; `--active` is
  deny-by-default for state-changing verbs and requires a typed `yes`). Also `shannon-ai-pentest` — a
  documentation/operating skill for **Shannon** by Keygraph, an autonomous **white-box** AI pentester
  that reads an app's source, runs **real proof-of-concept exploits** against the live app, and reports
  only proven findings. Documents the external **AGPL-3.0** `npx @keygraph/shannon` CLI (commands +
  flags), AI-provider/model-tier config (Anthropic/Bedrock/Vertex/proxy), the YAML engagement config
  (auth + login-flows + TOTP, scope avoid/focus rules, report filters), the workspace/report layout,
  and the safety rules. **Shannon is not vendored** — it is installed separately; this skill bundles no
  AGPL code, only original documentation with full attribution (verified accurate against the upstream
  docs).
- **Security architecture** — `edge-to-service-trust-boundary` (the HMAC-signed forwarded-identity
  contract between an API gateway/edge and the services behind it: the edge signs identity/tenant headers
  + a timestamp, downstream services verify with a constant-time compare and **fail closed**, reject
  replayed/skewed requests, **detect conflicts** when identity is resolvable from multiple sources, and
  still enforce their own authz; documents the `verify_signature=False`-then-trust, naked-header-trust,
  and fail-open anti-patterns — complements `auth-and-rbac` + `multi-tenancy-patterns`) and
  `kubernetes-workload-hardening` (runtime/manifest-layer hardening: pod/container `securityContext`,
  default-deny `NetworkPolicy` + explicit allows, **digest-pinned** images, resource requests/limits,
  **restricted PodSecurity** admission, least-privilege ServiceAccount/RBAC, and secrets via `secretRef`
  — the runtime layer atop the `dockerfile-*`/`docker-shared` image-build skills). Both are grounded in
  the cross-repo security gap analysis and fully genericized (no internal hosts, registries, namespaces,
  project IDs, or secrets).

Each ships `SKILL.md` + `README.md` + `references/` (the `zap-vapt-scanning` skill also bundles runnable
`scripts/`; `shannon-ai-pentest` is documentation-only for an external AGPL-3.0 tool). All are free of
internal service/registry/org names, paths, and secrets, verified by a scrub gate + per-skill
scrub-verifier (the two security-architecture skills additionally went through an 18-agent adversarial
verification — leak scrub + technical-accuracy + format — after which fixes were applied for recursive
log redaction, DNS-over-TCP egress + an explicit `kube-system` selector, and cryptographically secure
CSRF-token generation). Like the prior stack-specific sets, these are intentionally stack-specific and
not wired into the catalog/scaffold, so `claude-kit init` output is unchanged. The `docs/stack-skills/`
index is updated (43 skills).

### Changed

- **Extended 6 existing skills** with new sections + reference files: `fastapi-service-patterns`
  (API versioning + conditional routes), `python-dao-and-database` (MongoDB aggregation/bulk-upsert/index
  patterns), `temporal-config-driven` (idempotent schedule registration), `graphql-patterns` (advanced
  Apollo Client setup), `containerization-and-deployment` (Makefile dev workflow + Kerberos kinit
  bootstrap), `testing-conventions` (GitHub Actions test orchestration).
- **Security pass on existing skills** — extended `observability-and-logging` with a PII/secret
  **redaction structlog processor** (recursive sensitive-key denylist + content masking of emails, card
  runs, bearer tokens, and DB-URL credentials, plus an audit-event field allowlist) in a new
  `references/pii-redaction.md`; `testing-conventions` with a **security-regression** section (negative
  authz, cross-tenant/RLS isolation, IDOR, login lockout, signed-header trust) wired to a dedicated
  `pytest -m security` CI gate in a new `references/security-regression-tests.md`; `graphql-patterns`
  with a clarification that Apollo's `apollo-require-preflight` protects the transport but cookie/session
  auth still needs a CSRF token; and the **core** `security-and-hardening` skill with a CSRF
  synchronizer/double-submit-token pattern and a ban on disabling outbound TLS verification
  (`verify=False` / `rejectUnauthorized:false` / `NODE_TLS_REJECT_UNAUTHORIZED=0` / `curl -k`), with
  private-CA-bundle guidance.
- **Extended + trimmed `data-engineering-bigquery-gcs`** — added six grounded BigQuery patterns
  (parameterized queries, streaming inserts, in-memory `load_table_from_dataframe`, dynamic schema
  evolution via `update_table`, the `TimePartitioning` Python API, and a reusable `BigQueryUtils`
  wrapper) in a new `references/bigquery-advanced-patterns.md`; removed the unobserved GCS-client and
  pandas-ETL sections (now delegated to the new `gcs-file-storage-patterns` skill), dropping the stale
  `references/pandas-pipelines.md`.

### Fixed

- **Genericized an internal reference that escaped the 0.18.0 scrub** — `temporal-config-driven`
  reference files named an internal e-signature integration; replaced the example identifiers with
  neutral `Esign*` ones.
- **Removed a SQL-injection example** in `node-objection-knex` — replaced raw `whereRaw` string
  interpolation with bound parameters and documented it as an anti-pattern.

## [0.19.0] — 2026-06-20

**Add four granular Docker skills (backend/frontend Dockerfiles, shared building blocks, compose).**

### Added

- **4 granular Docker skills** under `skills/`, complementing the broader `containerization-and-deployment`
  skill with focused deep-dives derived from real production Python/FastAPI + React services:
  - **`dockerfile-backend`** — multi-stage Python/FastAPI Dockerfiles: builder/runtime split, slim vs
    alpine trade-offs, system deps (libpq/librdkafka/krb5), layer-cache ordering, venv copy, non-root
    user, multi-mode entrypoint, gunicorn+uvicorn, `HEALTHCHECK`.
  - **`dockerfile-frontend`** — React/Vite multi-stage builds: node(alpine) build → nginx runtime,
    lockfile-first caching, `VITE_*`/`REACT_APP_*` build args, runtime `envsubst`, nginx SPA history fallback.
  - **`docker-shared`** — shared base images from a private registry (tag vs `@sha256` digest pinning),
    `.dockerignore` conventions, shared compose fragments (YAML anchors, `x-` fields, external
    networks/volumes), and the build-arg-secret anti-pattern + BuildKit `--mount=type=secret` fix.
  - **`docker-compose`** — local-dev/orchestration: postgres/redis/kafka/temporal healthchecks wired to
    `depends_on: condition: service_healthy`, one-image-many-roles (MODE), env-specific compose files.
  Each ships `SKILL.md` + `README.md` + `references/`, cross-links `containerization-and-deployment`,
  and is fully genericized (no internal service/registry/org names, paths, or secrets) — verified by a
  scrub gate + adversarial critic. Like the 0.18.0 set, these are intentionally stack-specific and not
  wired into the catalog/scaffold, so `claude-kit init` output is unchanged. The `docs/stack-skills/`
  index is updated (22 skills).

## [0.18.0] — 2026-06-20

**Add a stack-specific skill collection (Python/FastAPI + React) and refine the secret guard.**

### Added

- **18 stack-specific engineering-convention skills** under `skills/` (auto-discovered by the plugin),
  encoding house-style patterns for FastAPI services, async Python, SQLAlchemy/DAO, Pydantic, Kafka,
  Temporal, multi-tenancy, React frontends, observability, auth/RBAC, containerization, testing,
  Alembic, BigQuery/GCS data pipelines, GraphQL, and modernization. Each ships `SKILL.md` + `README.md`
  + `references/`. A `docs/stack-skills/` index (catalog, technology-coverage matrix, gap analysis)
  documents the set. These are **intentionally stack-specific** — a deliberate departure from the
  stack-agnostic payload principle (golden rule #1) — and are **not** wired into the catalog/scaffold,
  so `claude-kit init` output is unchanged. All content is genericized (no internal service/repo/org
  names, paths, or secrets), verified by a scrub gate and an adversarial critic.

### Changed

- `hooks/scripts/guard-secrets.sh` now detects secret **values** (PEM private-key blocks, `AKIA…`,
  `sk_live_…`, Slack/GitHub tokens) instead of variable **names** (`SECRET_KEY`/`API_KEY`/`*PASSWORD*`),
  which false-positived on legitimate security/config documentation. Secret-file detection
  (`.env`/`.pem`/`.key`/credentials) is unchanged.

## [0.17.3] — 2026-06-17

**Fix: remove the two `UserPromptSubmit` prompt hooks that errored on every prompt.** Once the plugin's
hooks actually loaded (0.17.2), `skill-routing` and `learning-detection` — both `type: "prompt"` —
failed on every user message with `Schema validation failed` / `JSON validation failed`. Root cause: a
Claude Code **prompt hook may only return a yes/no decision** (`{ ok, reason?, impossible? }`); it
cannot inject context. Those two hooks told the model to return `{"continue": true, "systemMessage":
"<hint>"}` to *inject* a routing/learning hint — a shape the prompt-hook validator rejects, and a
capability prompt hooks don't have (context injection on `UserPromptSubmit` belongs to **command**
hooks via stdout / `hookSpecificOutput`). They had never worked — they didn't even load before 0.17.2.

### Removed
- **`skill-routing`** and **`learning-detection`** (`UserPromptSubmit` prompt hooks) from **both**
  channels — the plugin `hooks/hooks.json`, the CLI `HOOK_REGISTRY` (`src/claude_kit/hooks.py`),
  `templates/settings.json`, and the `standard` profile (`catalog/profiles.yaml`). Their function is
  already covered: Claude auto-selects skills from their descriptions, and durable learnings are
  recorded by the background `capture-learnings` job (verified working in 0.17.x) plus `/remember`.

### Docs
- Dropped the "two-sided capture" / learning-detection references from `docs/coverage-audit.md`,
  `docs/agentic-patterns.md`, `rules/agent-memory.md`, `skills/remember/SKILL.md`, `catalog/capture.yaml`,
  and `src/claude_kit/models.py`.

### Not adopted (deliberately)
- **Re-implementing them as deterministic command hooks** (keyword match → stdout hint) — skill
  auto-selection + background capture already cover the need, and a per-prompt hint adds noise; kept
  the kit simpler (reuse-first).

## [0.17.2] — 2026-06-17

**Fix: the plugin's hooks load (for real this time).** 0.17.1 wrapped `hooks/hooks.json` under a
top-level `hooks` key — necessary, but it uncovered a second problem the flat file had masked. Claude
Code **auto-discovers** `hooks/hooks.json` from the plugin root, yet `.claude-plugin/plugin.json` *also*
pointed its `hooks` field at the same `./hooks/hooks.json`. The loader then read the file twice and
failed with **`Hook load failed: Duplicate hooks file detected`** — so, again, none of the plugin's
hooks loaded. The manifest `hooks` field is reserved for *additional* hook files; the standard one is
loaded automatically and must not be re-declared. Every other Claude Code plugin (superpowers, hookify,
vercel, …) relies purely on auto-discovery. This affected only the **plugin** channel; the pip CLI was
always fine (it builds `.claude/settings.json` from `HOOK_REGISTRY`, `src/claude_kit/hooks.py`). After
upgrading, run `/plugin marketplace update claude-kit` → `/plugin update claude-kit@claude-kit` →
`/reload-plugins`, then `/doctor`, to confirm the error is gone.

### Fixed
- **`.claude-plugin/plugin.json`** no longer sets `hooks: "./hooks/hooks.json"`. The file is
  auto-discovered from the plugin root (and stays wrapped, per 0.17.1), so it now loads exactly once.

### Changed
- **`tests/test_plugin.py`** now reads the auto-discovered `hooks/hooks.json` directly (not via the
  manifest) and adds `test_manifest_does_not_redeclare_standard_hooks`, so the duplicate-load
  regression can't come back.

### Added
- **README** — a "Updating the plugin" snippet (`/plugin marketplace update` → `/plugin update` →
  `/reload-plugins`) in the plugin Quick-start section.

### Not adopted (deliberately)
- **Inlining the hooks into `plugin.json`** (the object form, which would also avoid the collision) —
  still kept external; the `UserPromptSubmit` routing and learning-detection prompts read far better in
  a dedicated file than inlined in the manifest.

## [0.17.1] — 2026-06-17

**Fix: the plugin's hooks now load.** `.claude-plugin/plugin.json` points its `hooks` field at a file
(`./hooks/hooks.json`), and Claude Code requires a *referenced* hooks file to be shaped like a
settings fragment — a top-level `hooks` record mapping events to matcher groups. The kit had shipped
that file as a **flat** event map since 0.7.0, so the plugin loader rejected it (`invalid_type … path:
["hooks"] … expected record, received undefined`) and **none of the plugin's hooks loaded** (the
destructive-command guards, context loaders, capture, and learning-detection). This affected only the
**plugin** channel; the pip CLI was always fine because it builds `.claude/settings.json` from
`HOOK_REGISTRY` (`src/claude_kit/hooks.py`), a separate source. Run `/reload-plugins` then `/doctor`
after upgrading to confirm the error is gone.

### Fixed
- **`hooks/hooks.json`** is now wrapped under a top-level `hooks` key (inner content otherwise
  byte-identical — every matcher group and prompt preserved). This matches every other Claude Code
  plugin that references a hooks file (superpowers, hookify, vercel, …).

### Added
- **`tests/test_plugin.py`** — a regression guard asserting the plugin hooks file is wrapped and
  well-formed (known events, non-empty `hooks` lists, `command`/`prompt` entry types), so a flat file
  can't ship again. Suite now 99 passing.

### Not adopted (deliberately)
- **Inlining the hooks into `plugin.json`** (the other valid shape) — kept the external file because the
  `UserPromptSubmit` routing and learning-detection prompts are long and read far better in a dedicated
  file than inlined in the manifest.

## [0.17.0] — 2026-06-17

**Make agent-side learning capture an init-time, cost-aware choice — and make it actually remember.**
The kit can now reflect on what *Claude itself* changed during a session and record durable learnings
into `.claude/agent-memory/` (recalled next session by `load-learnings.sh`), via a fully-detached
background `claude` job that **never blocks your session or next prompt**. How often that runs is the
token-cost knob, so it is now a question at `claude-kit init` (`capture_mode`) rather than a fixed
behavior — "everyone has their own way to memorize." Four modes (see `catalog/capture.yaml`):

- **`off`** — no auto-capture; record with `/remember` when you choose (zero background cost).
- **`session-end`** — one background capture when a session ends (~1/session). Lost on abrupt close.
- **`session-end-catchup`** *(default, recommended)* — adds a SessionStart **catch-up** that, on the
  next launch, captures any prior session that ended *without* being captured — i.e. one closed
  abruptly with Ctrl-C / a hard kill / a closed terminal, where `SessionEnd` never ran. ~1/session,
  robust to abrupt close.
- **`per-task`** — capture after each file-editing task (Stop), scoped to that task's edits via a
  line-count sentinel. Most resilient, highest token cost.

One script (`hooks/scripts/capture-learnings.sh`) backs all of it, dispatched by an argument
(`end`/`stop`/`catchup`); a per-transcript "done" marker lets a clean exit tell catch-up "already
handled," so a session is never captured twice.

**Two correctness fixes folded in (the previous SessionEnd capture looked done but did not actually
remember):**
- **Recall now works.** The background agent wrote the learning file but could not index it in
  `MEMORY.md`, which is the *only* file `load-learnings.sh` reads — so learnings were invisible to
  future sessions. Root cause: `.claude/` is a Claude-Code-protected path that `--permission-mode
  acceptEdits` cannot write from a detached, no-TTY background agent. The capture child now runs with
  `--permission-mode bypassPermissions` (safe here: file tools only, no shell, prompt-confined to
  `.claude/agent-memory/`), and the prompt makes indexing in `MEMORY.md` mandatory + self-verified.
  Round-trip (write → index → recall) verified end-to-end.
- **`load-learnings.sh` zero-entry crash** — `grep -c … || echo 0` emitted `"0\n0"` → `integer
  expected`; fixed with `|| true` + `${ENTRIES:-0}`.

Conservative + safe by construction (golden rule #1 — stack-agnostic, fail-safe): every mode degrades
to a silent no-op without `jq`/`claude`/a transcript or when the project has no `agent-memory/`, and
only spawns when there were actual file edits. The job inherits the user's logged-in auth, runs
hook-free (`--settings '{"disableAllHooks":true}'`); recursion is broken by `CLAUDE_KIT_NO_AUTOCAPTURE=1`
(passed to the child), which doubles as the user opt-out. `CLAUDE_KIT_CAPTURE_MODEL` optionally pins a
model (default: inherit the user's).

### Added
- **`capture_mode` init choice** — new `catalog/capture.yaml` (the four modes → hook sets, default
  `session-end-catchup`); a `Selection.capture_mode` field; an interactive prompt (profile-aware
  default: **lean → off**, otherwise the recommended catch-up); `--config` / `--defaults` support;
  `catalog.capture_mode_options()` + a branch-free `catalog._apply_capture_mode()` that swaps the
  capture hooks for the chosen mode (golden rule #6 — pure data + set op).
- **Three capture triggers** in `HOOK_REGISTRY`, all backed by the one `capture-learnings.sh`:
  `capture-learnings` (SessionEnd, `end`), `capture-learnings-catchup` (SessionStart, `catchup`),
  `capture-learnings-stop` (Stop, `stop`). The recommended default is wired into the plugin
  (`hooks/hooks.json`) and the no-pip fallback (`templates/settings.json`).

### Changed
- `catalog/profiles.yaml` — the standard profile no longer hard-lists `capture-learnings`; capture is
  installed by `capture_mode`, not profile membership (`load-learnings` recall stays profile-driven).
- **Docs** — `README.md`, `rules/agent-memory.md`, `docs/agentic-patterns.md` (Ch. 9),
  `docs/coverage-audit.md`, `skills/remember/SKILL.md`, and `CONTRIBUTING.md` describe the configurable,
  abrupt-close-robust capture.

### Fixed
- Background capture now reliably **indexes** learnings in `MEMORY.md` (was write-only → unrecalled).
- `load-learnings.sh` no longer errors on a zero-entry index.

## [0.16.0] — 2026-06-16

**Adopt a full React/Tailwind/Radix design-system rule set as always-on React overlay rules.** Three
manually-authored, production-grade design docs — `ui-design-system.md` (color/spacing/typography/
radius scales, card & badge & icon standards, accessibility), `ux-patterns.md` (status expression,
empty states, breadcrumbs, page archetypes/blueprints, button ordering, date formatting, data colors),
and `mobile-design-guidelines.md` (responsive breakpoints, touch targets, Capacitor native patterns) —
are now installed into `.claude/rules/` whenever the **React** frontend is selected. This closes a
long-standing gap: the kit already shipped the *readers* (`ui-ux-design` + `component-design` skills,
`ui-designer` agent) but not the *content* they pointed at, so a fresh install never created the design
docs they read.

Placement is **always-on React overlay rules** (wired purely through `catalog/stacks.yaml`
`overlay_rules` — no new scaffold mechanism, `resolve()` untouched per golden rule #6). Accepted
trade-off: ~3k lines of design rules load every session on React projects, in exchange for the design
system being authoritative and always present. The three files live **only** in
`templates/stacks/frontend/react/rules/` (golden rule #1 — stack content stays in overlays).

IP boundary: the design **decisions** are preserved verbatim (radius, touch targets, status-via-Badge,
button ordering, date formats, chart standards, the four page archetypes and their blueprints/compound
tables), while every app-specific reference was neutralized — product/persona/route identity, concrete
`src/...` module paths and named app components, the 52-page inventory, dated migration backlogs, the
domain KPI glossary and INR locale specifics, project-specific lint-rule identifiers, and brand hex
values (→ `#______` placeholders, matching the existing `design-system-compliance.md` style).

### Added
- **Three React overlay rules** under `templates/stacks/frontend/react/rules/`:
  `ui-design-system.md`, `ux-patterns.md`, `mobile-design-guidelines.md` — registered in
  `catalog/stacks.yaml` → `frontend.frameworks.react.overlay_rules`, installed into `.claude/rules/`
  only when React is selected. Consumed by the React-gated `ui-ux-design` / `component-design` skills
  and the `ui-designer` agent.

### Changed
- **Conflicts resolved in favor of the new files.** `design-system-compliance.md` — the placeholder
  token table is replaced by a thin pointer naming `ui-design-system.md` (+ `ux-patterns.md` /
  `mobile-design-guidelines.md`) as the source of truth ("if anything here conflicts, that file wins"),
  keeping only the concise always-on enforcement hook. `react-patterns.md` — the "Accessibility
  specifics (Tailwind + Radix)" rules (contrast table, `p-3 -m-3` touch target, clickable-non-button)
  are trimmed to a cross-reference into `ui-design-system.md` §Accessibility, retaining two
  React-specific review reminders.
- **Reader paths repointed** from `docs/references/ui/...` → `.claude/rules/...` so the existing
  reader-loop connects to the now-installed content: `skills/ui-ux-design` (steps 1–2 + References,
  with the design-system rule marked authoritative over the inline quick-check table),
  `skills/component-design` (read whichever of the overlay rule or `docs/references/ui/` is present),
  and `agents/ui-designer` (overlay rule added to its candidate locations, defensive "if one exists"
  framing kept — the agent is core/un-gated and must not assume the React overlay is present).

### Notes
- `docs/references/ui/sidebar-navigation.md` is **not** supplied by the kit; the skills reference it as
  project-specific/optional.

## [0.15.0] — 2026-06-16

**Adopt a set of internal engineering personas & skills** (a private Claude Code plugin marketplace —
11 agents + 29 skills across 7 plugins: engineer, designer, pm, context-gen, staff-em, staff-sdet,
staff-pm). Those plugins are excellent but heavily **stack-bound** (FastAPI/SQLAlchemy/Pydantic/React/
Tailwind/Radix/Zod/Temporal/Kafka/Langfuse, against an internal `.ai/` doc convention). Mirroring all
40 files into a stack-agnostic kit would leak framework specifics into the core (golden rule #1) and
duplicate components claude-kit already ships (golden rule #3). So they were adopted **reuse-first**.

An 81-agent adversarial workflow mapped every item against the live inventory, two-sided-verified each
verdict, and synthesized the landing zones. Tally of the 40: **11 map** (already covered — adopt
nothing), **18 extend** (a real delta folded into the nearest existing component), **5 adopt-stack**
(framework substance → existing overlays), **5 adopt-org** (senior-review personas → scope-gated org
layer), **1 adopt-core** (genuinely new + stack-agnostic). Net: **2 new core skills, ~10 surgical core
extends, 1 new React overlay rule + FastAPI/React overlay enrichments, 5 new org components** — zero
stack leakage into core, zero diluting duplicates. IP boundary: technique-and-structure only, no source
text copied; every source-internal reference (internal doc conventions, internal field/service names, numeric
heuristics) stripped or genericized.

Three deliberate decisions: **(1)** Temporal/Kafka/Langfuse are **not** added as selectable stacks —
they would be new top-level `stacks.yaml` *kinds*, which `resolve()` reads through fixed
frontend/backend/database accessors, so they'd require resolver/model/prompt code (golden rule #6).
Recorded as future work. **(2)** the context-layer *generator* folds into `context-engineering` as a
mode (not a competing docs skill — golden rule #3). **(3)** the senior-review **product-lens** personas
go to the org layer (install only at `scope == organization`); the **engineering-lens** deltas fold
into existing core gates.

### Added
- **`skills/bug-hunt`** (new core skill, standard+; the sole adopt-core). A proactive, source-only,
  spec-free exploratory bug hunt: map the feature, sweep a fixed scenario taxonomy (input edge cases ·
  an error state per failure point · state · race/concurrency · rendering · authorization), rate
  findings on the kit's Critical/High/Medium/Low/Cosmetic model with `path:line` + repro + root cause,
  then a systemic-pattern pass + top-3. Cross-refs `debugging-and-error-recovery`,
  `code-review-and-quality`, `senior-tester`, `auditor` to protect auto-selection.
- **`skills/test-plan-review`** (new core skill, standard+). A forward-looking review of a *proposed*
  test plan / test-infra design **before tests exist**: data-generation strategy, validation depth via
  a field-drift matrix, infra failure modes, coverage-by-domain, each gap tied to a preventable
  incident. Distinct from `senior-tester` (verifies already-executed tests).
- **Org senior-review tier** (organization scope only): `staff-pm-reviewer` agent (product-lens,
  read-only) + `review-scope`, `review-sprint-plan`, `review-ux-flow`, `review-sprint` skills. Wired via
  `catalog/org.yaml` (`new_agents`/`new_skills`) into the `product-to-code` and `quality-and-review`
  packs (`existing: false`).
- **React `design-system-compliance.md` overlay rule** (Tailwind/Radix/Lucide): token-not-arbitrary-
  value enforcement, one set of component variants, radius/spacing/icon scales, `cn()` class-merge,
  explicit light/dark scope — palette parameterized to the project. Registered in `stacks.yaml` React
  `overlay_rules`.

### Changed
- **10 core extends**, each folding one verified delta into an existing component (neutral phrasing):
  `context-engineering` (generate/refresh a persistent cross-linked comprehension layer — the `.ai/`
  technique, genericized); `planning-and-task-breakdown` (cross-service/multi-repo coordination +
  task-type prompt templates + a portable cross-LLM prompt); `deprecation-and-migration` (Pre-Removal
  Safety Check — sweep every consumer surface incl. the silently-breaking test mock/patch import
  paths); `sprint` (proactive agent capacity/replacement planning + run-the-checks-for-real post-sprint
  report); `orchestrator` (Live-Sprint Health monitoring); `archive-sprint` (verify checks actually
  ran before archiving); `em-reviewer` (Verify-Claims-Against-the-Codebase checklist + eval/HITL line);
  `senior-tester` (a standing suite-architecture audit mode); `technical-architect` (a thin eval / HITL
  / staged-rollout cross-ref to the owning rules); `refresh-docs` (run a deterministic freshness script
  first if present).
- **FastAPI overlay** (`fastapi-patterns.md`) enriched: HTTP method→status + domain-error→status
  mapping (**reconciled** with — not contradicting — the file's existing router-maps-to-HTTPException
  rule), service-layer logging discipline + N+1/soft-delete/method-naming, snake-case-on-the-wire,
  reading live DB state safely, changed-files→test routing, schema-derived contract fixtures, and the
  concrete pre-removal grep recipe behind the agnostic Pre-Removal Safety Check.
- **React overlay** (`react-patterns.md`) enriched: an accessibility section (Tailwind `text-gray-*`
  contrast table, `p-3 -m-3` touch-target pattern, clickable-`div` keyboard recipe, the
  `@/components/ui`/Radix focus/keyboard allowlist), changed-files→test routing, and strict Zod/Vitest
  contract fixtures.
- `profiles.yaml`: `bug-hunt` + `test-plan-review` added to **standard** (inherited into enterprise).

### Explicitly not adopted (mapped to existing)
engineer/code-reviewer → `sdlc-code-reviewer`; frontend/backend-developer → `senior-*-dev`;
pm/feature-scoper + scope-feature → `scope`; the monolithic staff-em-reviewer → split across
`acceptance-reviewer`/`technical-architect`/`em-reviewer`/`merge-reviewer`/`devils-advocate`;
verify-sprint → `acceptance-reviewer`+`sprint`+`archive-sprint`; designer/audit-ui/review-styles/
component-spec → `ui-ux-design`/`accessibility-review`/`component-design`/`ui-designer`;
context-gen/update → `refresh-docs`. Each would be a near-duplicate (golden rule #3).

## [0.14.0] — 2026-06-16

A **third improvement brief** — six engineering *techniques* observed in Anthropic's Claude Code system
prompts, **reimplemented from scratch in claude-kit's own vocabulary** (gates, severity, RARV,
profiles, scopes, Orchestrator, CONTINUITY, agent-memory). No source text was copied, quoted, or
closely paraphrased — the IP boundary is technique-and-structure only. Run through the kit's reuse-first
mapping, the decisive finding repeated once more: every pattern already had a natural home, so all six
land as **extensions of existing rules/agents/skills/hooks** — **zero new agents, zero new rule files**
(core counts unchanged: 28 agents · 50 skills · 23 rules).

Two deliberate divergences from the brief's *inferred* file paths (it invited path verification):
**(P0-1)** the autonomous-action posture lives in `rules/agent-guardrails.md` §3 (execution discipline),
not `rules/risk-classification.md` (tier assignment) — cross-referenced from the restricted tier;
**(P2-1)** the implementer house style extends `templates/CLAUDE.md` "Surgical Changes" (the kit's
always-in-context house-style home) rather than adding a new rule that would near-duplicate it and
`code-organization.md` (golden rule #3).

### Added
- **P0-1 — autonomous-action safety** (`rules/agent-guardrails.md` §3, always-on). A **block / confirm /
  allow** posture over irreversible & outward-facing actions (force-push, history rewrite, branch/tag
  deletion, destructive migration, bulk deletion, secret access, publish/send/post), a **verify-the-
  target-before-destroying** step (stop if what you find contradicts how the task described it), and the
  affirmative §1 rule that **untrusted/injected content never authorizes an action**. Cross-ref from
  `rules/risk-classification.md`; one-line pointers from `developer`, `devops-engineer`, and both
  `migration-specialist` overlay agents.
- **P0-2 — anti-fabrication of verdicts** (`rules/quality-gates.md` §2.5 + §1, always-on). A gate verdict
  (PASS/FAIL) is valid **only** when it cites the real command + captured output (or the `file:line`
  finding); a fabricated, assumed, or partial-output-based verdict is **auto-Critical**; reading a
  still-running lane's output and calling the gate done is forbidden. Reinforced in
  `rules/agent-guardrails.md` §2 and `rules/rarv-cycle.md` ("cite it", not just "run it").
- **P1-3 — plan-phase critique before approval.** The `spec-doc-writer` now runs an explicit
  **self-critique** in its RARV cycle (always-on, wherever planning runs); and in **standard+** the
  Orchestrator runs `devils-advocate` once on the spec + dev-docs **before EM approval is final**
  (new Stage PC / `mandatory-workflow.md` §1e.5) — an UPHELD verdict routes back to the Spec Writer and
  the spec gate stays open. `devils-advocate` extended to a plan-critique mode (was code/tests only).
  **lean** keeps self-critique only (it doesn't install the agent).

### Changed
- **P1-1 — memory hygiene** (`rules/agent-memory.md`, always-on): verify-before-trust (confirm a
  recalled file/flag/command still exists before relying on it), selective attachment with cited
  sources, and reconciliation (committed `CLAUDE.md`/`rules/*` win over a conflicting memory). A
  start-of-turn line added to `rules/continuity.md`; a staleness check added to the `remember` skill.
- **P1-2 — resume snapshot** (`rules/continuity.md`, always-on): a small structured
  `.claude/state/pipeline-snapshot.json` (profile/scope, mode, stage, per-lane status,
  `last_gate_passed`, open findings by severity, next action) the Orchestrator maintains alongside
  CONTINUITY; on resume it is **reloaded as context, not re-executed** (no re-running setup, no
  re-applying committed edits, no re-opening passed gates). Wired into the `sdlc` skill + `orchestrator`;
  `load-continuity.sh` now ensures `.claude/state/` exists in plugin context (the pip installer already
  creates and gitignores it).
- **P2-1 — implementer house style** (`templates/CLAUDE.md` "Surgical Changes", always-on): delete the
  superseded path instead of leaving a backwards-compat shim (unless compat is required), validate at
  the boundary not redundantly in every layer, cite code as `path:line`, and (cross-ref to
  `rules/documentation.md` §6, no duplication) no change-narration comments. The `sdlc-code-reviewer`
  gains a **Change Hygiene** check group (shim-without-requirement = Medium; redundant re-validation =
  Low; narration comment = Low); reinforced in the `developer` agent.

### Notes
- **No `resolve()` / catalog changes** — all six are payload-content edits, so the
  `lean⊊standard⊊enterprise` subset, MCP-gating, and no-Docker invariants are untouched.
- `docs/coverage-audit.md` gains a Brief-#3 section; `docs/architecture.md` adds the standard+ plan-
  critique node.

## [0.13.0] — 2026-06-15

A **second improvement brief** (external self-review, post-0.12.0) — Item 0 (a covered-vs-gated audit)
+ P0-1/P0-2, P1-1/P1-2/P1-3, and six P2 items — run through the kit's mandated **adversarial
reuse-first map→verify** (a 24-agent map→verify pass). The decisive finding repeated from last time:
several premises were **overstated** against the live files (migration safety was already largely
enforced; the README "no PyPI yet" text was simply stale; the README is already progressively
disclosed). The result is a mix of **two new gates wired as data, one new live backend stack, and
targeted extensions** — **zero new agents/skills/rules** beyond what already existed (core counts
unchanged: 28 agents · 50 skills · 23 rules).

### Added
- **Item 0 — `docs/coverage-audit.md`.** The justification record the briefs kept eliding: every
  "already covered" capability classified **GATED (enforced) / RULE (always-on) / SKILL-DOC
  (advisory)** with file evidence. Verifies rollback (GATED enterprise-only; RULE elsewhere), cost
  (DOC by design), migration safety (overlay-advisory + enterprise rollback), accessibility, and
  flags the one *looks-enforced-but-isn't* trap (the `accessibility-review` skill's internal "Quality
  gates" heading is **not** a gate token).
- **P0-1 — `contract-clear` reaches the default `standard` profile** (API stacks), not just
  enterprise (`catalog/profiles.yaml`). It still self-skips when the stack exposes no API contract
  surface, so non-API projects are unaffected. *(Deliberate posture change: 0.12.0 placed it in
  enterprise under golden-rule-#6 "heavyweight gates default to enterprise"; the brief explicitly
  authorizes promoting it because breaking-change detection is table-stakes for the headline FastAPI
  backend. Documented, not silent.)* Owned by `merge-reviewer`; quality-gates §4 + mandatory-workflow
  §2d + the api-change-report template updated to say "standard+".
- **P1-1 — a live Go backend stack** (Go · stdlib **net/http**): a pure `catalog/stacks.yaml` entry +
  `templates/stacks/backend/go/net-http/rules/go-patterns.md` overlay + exact `go` commands
  (`go build ./...`, `go test ./...`, `go vet`, `gofmt`). Chosen over Node/Express precisely because
  its build/test command shapes differ most from npm/pip — the strongest test of the stack-agnostic
  claim. The one supporting code change: a **`build`** key added to `_BACKEND_CMD_KEYS` (compiled
  backends surface a build command; interpreted ones leave it empty). No `resolve()` branch.
- **P1-2 — `accessibility-clear` gate** at organization scope, **`regulated` strictness only**
  (`catalog/org.yaml` `extra_gates`). Owned by `acceptance-reviewer` (read-only, already present at
  standard+), drives the existing `accessibility-review` skill over changed UI (WCAG-AA), self-skips
  when no UI surface. Wired in `org.yaml` only, so the `lean⊊standard⊊enterprise` profile invariant is
  untouched.
- **`examples/react-fastapi-postgres-feature/`** (P2-2) — a clearly-labelled **synthetic** end-to-end
  walkthrough: request → feature-spec → story breakdown (coverage gate) → gate verdicts (incl. one
  defect-loop cycle and a Devil's-Advocate CONFIRMED line) → sample PR diff. Repo reference (like
  `docs/`), **not** bundled into the wheel.
- **`docs/eval-harness.md`** (P2-4) — a fill-in template to measure the pipeline with vs without the
  gates (which gate caught which defect), built on `rules/evals.md` §6 median-of-N. Ships **no**
  numbers by design (an eval result is environment-specific); honesty rules included.
- **Self-test matrix** (P2-5) — a parametrized test sweeping **every live frontend × backend ×
  database × profile × scope** (now 24 combos incl. Go), each resolved + installed + validated +
  Docker-checked. Driven off `catalog.list_options`, so new live stacks auto-join with no test edit.

### Changed
- **P0-2 — migration safety made explicit.** Both `migration-specialist` overlays (postgres + mongodb)
  already mandated expand/contract, reversible down-path, and idempotent backfill *as agent guidance*;
  added the explicit hard rule **"no destructive drop in the same release as the code that stops using
  the old shape"** with **severity** to the always-on overlay RULES (`postgres-patterns.md`,
  `mongodb-patterns.md`) — so it lives in a rule, not only an agent prompt. (Same-release destruction
  = at least **High**.)
- **P1-3 — the PyPI story reconciled.** `claude-code-kit` **is** published (latest 0.12.0); the README
  install block, troubleshooting row, and a stale `changelog-v0.10.0` badge said otherwise. Install is
  now `pip install claude-code-kit`; the changelog badge is de-versioned (self-healing); the CI
  publish machinery (`publish.yml`) was correct and left untouched.
- **P2-3 (on-ramp, minimal)** — added an **Examples** nav link + pipeline pointer only; the proposed
  full README restructure was **rejected** (see below). Pipeline gate table + `docs/architecture.md`
  diagram updated for `contract-clear` (standard+) and the Go stack.

### Not adopted (deliberately — premise overstated or against the kit's design)
- **A dedicated migration GATE token (P0-2).** Migrations are overlay-conditioned and not every-run;
  `resolve()` can't emit stack gates without a branch. Strengthened the always-on overlay rules +
  reviewer agents instead — enforcement via review + the enterprise rollback gate (`pipeline-green`),
  per the coverage audit.
- **Node/Express as the new backend (P1-1).** Chose **Go** instead — its command shapes differ more
  from the existing npm/pip stacks, which is the whole point of the breadth test. Express/Vue/Svelte/
  Django remain `planned`.
- **A full README restructure + GIF (P2-3).** The README already uses progressive disclosure
  (`<details>`); a big move-to-`docs/` churn is negative-value and a GIF can't be produced here. Added
  only the example link. (Recording a demo GIF is a human follow-up.)
- **Relocating the CHANGELOG "Not adopted" blocks to `docs/decision-log.md` (P2-6).** Those blocks are
  a **marketed feature** the README links to; moving them would break that cross-reference for low
  value. Added a forward-looking note in `CONTRIBUTING.md` instead (split later *only if* the README
  link is updated in the same change).
- **Repo About-box metadata (P2-1)** — host config outside the payload; `gh` is unavailable here.
  Human follow-up: `gh repo edit ajyadav013/claude-kit --description "Config-only, stack-agnostic
  autonomous-SDLC scaffolder for Claude Code (plugin + pip)" --add-topic claude-code --add-topic
  claude-code-plugins --add-topic sdlc --add-topic ai-agents --add-topic agentic-coding --add-topic
  claude-skills`.

## [0.12.0] — 2026-06-15

An **improvement brief** (external self-review, no repo access) proposed ~15 changes — four P0, five
P1, six P2. Run through the kit's own mandated **adversarial reuse-first mapping** (an 18-agent
map→verify pass), **every substantive (P0/P1) item resolved to _extend an existing component_, not add
a new one** — the brief, written without the repo, repeatedly proposed agents/gates/skills that already
ship. The result is **one new quality gate, one new artifact template, one new slash command, and a set
of surgical edits to existing files — zero new agents, skills, or rules** (counts unchanged: 28 core
agents · 50 skills · 23 rules). Config-only, stack-agnostic, no Docker, no new `resolve()` branches.

### Added
- **`contract-clear` quality gate** (enterprise profile; API-exposing backend stacks only). A
  pre-merge **API backward-compatibility** gate **owned by the existing `merge-reviewer`** (not a new
  agent): it diffs the API contract against the base branch (`git show <base>:<contract>`), classifies
  each delta by the kit's severity model (removed/renamed endpoint or field, narrowed type, new
  required field, removed status code = **Critical/High**), and blocks a breaking change that lacks an
  approved migration note + version bump. **Self-skips** when the stack has no contract surface, so it
  is inert for non-API projects. Wired as **data** in `catalog/profiles.yaml` (enterprise gate list),
  documented in `rules/quality-gates.md` §4, and sequenced as the mechanical counterpart to
  `mandatory-workflow.md` §2d. Builds **on** §2d's existing manual breaking-change check rather than
  replacing it.
- **`templates/artifacts/api-change-report.md`** — the `contract-clear` gate's output artifact
  (contract source · base ref · added/changed/removed tables with per-row severity · backward-compat
  verdict · affected consumers). Installs with the other artifact templates.
- **`/claude-kit:abort`** slash command (`commands/abort.md`) — a guided, **reversible** mid-pipeline
  cleanup: confirm a run is in progress, remove **only the worktrees this run created**, mark
  `CONTINUITY.md` aborted. Deliberately **not** a `claude-kit abort` CLI subcommand (a destructive
  one-shot CLI for "remove worktrees" is exactly the kind of irreversible action the kit gates).

### Changed (surgical extensions to existing components)
- **`skills/ci-cd-and-automation`** — named **Blue/Green vs Canary** as an explicit deployment-strategy
  subsection (blue/green was never named anywhere in the kit; cross-refs the existing Rollout Decision
  Thresholds). *(P0-1 — the only real gap; see "Not adopted" for the rest of P0-1.)*
- **`rules/devops-observability.md` + `agents/observability-engineer.md`** — Observability Ready now
  requires, **for a hot / SLO-bearing backend path**, an empirical load run (drive the existing
  `load-testing` skill) that meets its p95/p99 latency, error-rate, and throughput budgets; a budget
  breach is **High**. Recorded in the `quality-gates.md` §4 row. No new gate, no new agent. *(P0-3)*
- **`agents/dependency-scanner.md`** — added a **Cadence Mode** (a whole-project, scheduled
  supply-chain maintenance pass: batch grouped upgrades, defer triage to `security-and-hardening`,
  re-run the existing gates on applied upgrades). Scheduling is left to org CI (the kit has no
  time-driven hook). No new skill. *(P0-4)*
- **`rules/model-tiers.md`** — added a **profile cost expectations** subsection (relative, non-currency
  ballpark: lean cheapest → enterprise heaviest, noting enterprise still runs only four opus agents).
  *(P1-1)*
- **`skills/sdlc` + `agents/orchestrator.md`** — `/sdlc` now **detects an in-progress run** from
  `CONTINUITY.md` and offers **resume** (re-enter at the first gate after the last PASS, read from the
  orchestrator's `PIPELINE:` state line) **vs restart**; the orchestrator's Stage-7 summary now reports
  per-gate PASS/FAIL + severity + PR-or-ABORTED and **tears down this run's worktrees**. *(P1-2, P1-3)*
- **`rules/mandatory-workflow.md`** — §2a now states the **worktree lifecycle** (one per lane → merge
  after gates pass → remove after the PR is raised or the run is aborted); §2d gained a note pointing
  at the mechanical `contract-clear` counterpart. *(P1-3)*
- **`rules/continuity.md`** — added a **Concurrency** subsection (one live `CONTINUITY.md` per working
  dir; use a worktree per concurrent `/sdlc`; `agent-memory` is intentionally shared, not namespaced).
  *(P1-4)*
- **`src/claude_kit/validator.py` + README** — `claude-kit doctor` now reports **platform visibility**:
  on Windows without `jq` it WARNs (actionable: run under WSL/Git Bash; config + CLI work natively
  regardless) and on Windows *with* `jq` it confirms a POSIX shell is providing the hooks — **never a
  failure**. README gained a Windows prerequisites note + troubleshooting row. *(P1-5)*

### Not adopted (deliberately — the kit already covers these)
- **P0-1 `release-manager`/`release-ready`/`rollback-safety` (new agent + gate + rule).** Release &
  rollback are **already owned by `devops-engineer`** (and the Pipeline Green gate already requires a
  *verified* rollback + runbook); canary, feature flags, staged rollout, and rollback are already
  covered in depth by the `shipping-and-launch` skill. Only "blue/green was never named" was a genuine
  gap — fixed above as one subsection, no new components.
- **P0-2 `contract-reviewer` agent in the _standard_ profile.** Reused `merge-reviewer` instead of a
  new agent, and placed the gate in **enterprise** (heavyweight gates default to enterprise per the
  profile policy), not standard. It also **builds on** `mandatory-workflow.md` §2d rather than
  duplicating it.
- **P0-3 `performance-engineer` agent + standalone performance gate.** Folded into the existing
  Observability Ready gate + `observability-engineer` + `load-testing` skill.
- **P0-4 `dependency-maintenance` skill.** Folded into the existing `dependency-scanner` agent as a
  mode; no competing skill.
- **P1-1 `cost-estimate` skill + a per-run cost hook.** A doc subsection in `model-tiers.md` conveys
  the expectation without a runtime token-accounting surface the kit can't reliably measure.
- **P1-3 a `run-report` subsystem / structured run trace.** Already covered by `CONTINUITY.md` working
  memory + the orchestrator's Stage-7 summary; only the genuine gaps (worktree teardown + clean abort)
  were added.
- **P1-5 a PowerShell hook port.** The hooks stay POSIX `.sh`; `doctor` now tells Windows users to run
  under WSL/Git Bash. Porting every guard to PowerShell would double the maintenance surface for a
  shell most users already have via WSL/Git Bash.
- **The P2 items** (repo metadata, PyPI publish, listing submissions) that require a human / `gh` are
  left as follow-ups; the **E2E worked example**, **positioning section**, and **README on-ramp** were
  partly addressed (a "How claude-kit compares" positioning block + the adoption row were added).

## [0.11.3] — 2026-06-15

A field review of a **reference table of ecosystem repos** — official + community **MCP-server
directories** ([modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers),
[wong2/awesome-mcp-servers](https://github.com/wong2/awesome-mcp-servers),
[appcypher/awesome-mcp-servers](https://github.com/appcypher/awesome-mcp-servers)), **Cursor-rules**
collections ([PatrickJS/awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules),
[sanjeed5/awesome-cursor-rules-mdc](https://github.com/sanjeed5/awesome-cursor-rules-mdc)), a
**community skills** index ([GetBindu/awesome-claude-code-and-skills](https://github.com/GetBindu/awesome-claude-code-and-skills)),
and a **plugins** marketplace ([ComposioHQ/awesome-claude-plugins](https://github.com/ComposioHQ/awesome-claude-plugins)) —
run through the same adversarial map→verify pass (six candidates surfaced, each refuted against the
actual kit files). Exactly **one** survived. (anthropics/skills, wshobson/agents,
hesreallyhim/awesome-claude-code, rohitg00/awesome-claude-code-toolkit, and
anthropics/claude-plugins-official were re-confirmed at **zero** from prior reviews.)

### Added
- **`catalog/mcp.yaml`** — a new opt-in **`sentry`** MCP server (error monitoring / issue triage:
  top unresolved issues, stacktraces, performance & trace data, Seer root-cause analysis). This fills
  a gap the kit had already *designed in*: `agents/incident-responder.md` explicitly says *"If an
  error-tracking / monitoring integration is connected (e.g. via an MCP), pull the top unresolved
  issue + event trend"* and lists an "error-tracking issue" as a triage signal — yet no catalog entry
  fulfilled it, even though the kit ships both `incident-responder` and `observability-engineer`
  agents. Uses the **hosted OAuth HTTP endpoint** (`https://mcp.sentry.dev/mcp`, matching the
  `linear`/`docs` http style) so **no credentials are generated**. NOT bundled — only referenced; the
  server's source is **FSL-1.1-Apache-2.0 (source-available)**, flagged inline in the label exactly
  like the `repowise` AGPL note (a self-hosted/token `npx @sentry/mcp-server` alternative is
  documented in a comment). Opt-in (catalog default stays *none*), stack-agnostic, zero resolver
  change. (+2 tests, 80.)

### Not adopted (deliberately, per the assessment)
- **Semgrep MCP** (MIT, modelcontextprotocol directories) — SAST is already owned by `owasp-reviewer`
  + `security-reviewer` + `secret-scanner` + `dependency-scanner`, which follow the kit's "shell out to
  an installed CLI via Bash" pattern (`gitleaks detect`, `pip-audit`/`npm audit`); `owasp-reviewer`
  can run `semgrep --config auto` today with no catalog change. An MCP would add a privilege surface
  for zero new capability (`agent-guardrails §4`: treat MCP servers as untrusted until reviewed).
- **Composio `connect-apps` MCP** (ComposioHQ) — a closed commercial broker holding one key to authed
  **write** access across 500+ SaaS apps via an external relay. It overlaps the existing
  `github`/`linear`/`jira` servers and is the textbook supply-chain + data-egress risk that
  `agent-guardrails §4` and `human-in-the-loop` (outward-facing actions = mandatory STOP) warn
  against. Contradicts the catalog's deliberate one-server-per-purpose, least-privilege posture.
- **PatrickJS/awesome-cursorrules, sanjeed5/awesome-cursor-rules-mdc** (CC0) — overwhelmingly
  *stack-specific* `.cursorrules`/`.mdc` files (one per framework/language), which cannot enter the
  agnostic core. The one cross-cutting near-miss — anti-sycophancy *directed at the user* (resist
  manufactured urgency/authority) — is already expressed in `code-review-and-quality` ("Push back;
  sycophancy is a failure mode"), `idea-refine`, and `interview-me`, and its residual angle sits
  awkwardly against `human-in-the-loop`'s human-as-authority contract. The generator tool is out of
  scope for a config-only kit.
- **GetBindu skills** (Apache-2.0 index) — `should-i-care` (CVE applicability triage) duplicates the
  "Triaging Dependency Audit Results" decision tree in `security-and-hardening` + `dependency-scanner`
  (A06) and depends on a global `~/.config` state file foreign to the per-project `.claude/` model;
  `claudemd-auditor` is meta/out-of-SDLC-scope and covered by `context-engineering` + the harness's own
  `claude-md-management` skills.
- **Re-confirmed zero** — anthropics/skills (grew 8→17 skills, still document-processing/source-available/
  covered), wshobson/agents (stack-specific/covered), hesreallyhim & rohitg00 (meta-lists/aggregators),
  anthropics/claude-plugins-official (distribution marketplace).

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
