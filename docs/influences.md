# Influences & what we adopted

claude-kit is built **reuse-first**. We periodically review excellent open-source projects and adopt
**only the genuinely-new ideas** — never duplicating what the kit already does (near-duplicates would
dilute Claude's ability to auto-select the right skill). Each adoption follows the same method:
**fetch the real source → adversarially map it against the kit's existing files → ship only the
non-duplicative gaps**, minimally and catalog-wired.

| Source | What we learned | What we shipped | Since |
|---|---|---|:--:|
| **Agentic Design Patterns** — A. Gulli ([coverage map](agentic-patterns.md)) | Reasoning, guardrails, resilience, human-in-the-loop, evals, and tool design as first-class agent disciplines | 8 agent-operation rules + [`docs/agentic-patterns.md`](agentic-patterns.md) | `0.4.0` |
| **[ponytail](https://github.com/DietrichGebert/ponytail)** | YAGNI / anti-over-engineering as an explicit recurring pass; deferral-debt tracking; surfacing the active autonomy level; a pre-code reuse gate | `over-engineering-review` & `simplification-debt` skills, the `load-autonomy` hook, median-of-N in `evals`; later the pre-code **Reuse/YAGNI gate** (`mandatory-workflow` §2a.5) | `0.8.0`, `0.33.0` |
| **[GitHub spec-kit](https://github.com/github/spec-kit)** | Spec → tasks → **analyze** coverage gate; tasks → tracker issues; stable requirement IDs + assumptions in specs | Wired the (previously orphaned) `story-planner` as the **coverage gate (1f)**, a tracker-agnostic `task-tracker-sync` skill, and enriched the feature-spec template | `0.9.0` |
| **[protectai/llm-guard](https://github.com/protectai/llm-guard)** | Input→model→output guardrails for LLM features — prompt injection, PII vault, treating model output as untrusted | **Opt-in** "LLM / AI Feature Security" guidance in `security-and-hardening` + the advisory `warn-llm-io` hook (warns, **never blocks**) | `0.10.0` |
| **[repowise](https://github.com/repowise-dev/repowise)** | Runtime codebase-intelligence — hotspot (churn × complexity), co-change coupling, and change-risk as *advisory* review input | Hotspot/coupling/bus-factor guidance in `code-review-and-quality` (derivable from `git log` alone) + an **optional** `repowise` MCP fragment in the catalog (advisory, never a gate) | `0.11.0` |
| **Improvement brief** (external self-review) | API backward-compat as a gate; load-against-SLO as a release criterion; supply-chain maintenance cadence; pipeline resumability, clean abort, and worktree lifecycle; pipeline cost/concurrency/cross-platform transparency | The enterprise **`contract-clear`** gate (owned by `merge-reviewer`) + `api-change-report` template; a load-vs-SLO criterion in Observability Ready; dependency **Cadence Mode**; `/sdlc` resume-vs-restart, `/claude-kit:abort`, worktree teardown; cost/concurrency/Windows notes — **9 surgical extensions, 0 new agents/skills/rules** | `0.12.0` |
| **Improvement brief #2** (external self-review) | The covered-vs-**gated** distinction (a skill ≠ a gate); enforce API breaking-changes by default; expand/contract migration safety; back the stack-agnostic claim with a compiled backend; WCAG as a regulated gate; reconcile the PyPI story; ship a worked example + a self-test matrix | [`docs/coverage-audit.md`](coverage-audit.md); **`contract-clear` promoted to `standard`**; a live **Go/net-http** backend; the **`accessibility-clear`** regulated gate; explicit migration-drop rules; a synthetic [`examples/`](../examples/) run; an eval-harness template; a profile×stack×scope self-test matrix — **2 gates wired + 1 stack, 0 new agents/skills/rules** | `0.13.0` |
| **[OpenSpec](https://github.com/Fission-AI/OpenSpec)** | Delta-specs — change-scoped artifacts describing only what a change adds / modifies / removes | A `change-proposal.md` delta-spec template (keyed to stable `R#` ids) + a "full vs delta spec" decision in `spec-driven-development` | `0.34.0` |
| **gstack "Iron Law" + [superpowers](https://github.com/obra/superpowers)** `systematic-debugging` | Bounding blind fix attempts on a single bug | The **3-strike fix-attempt rule** in `agent-resilience` (each attempt a distinct hypothesis; at the 3rd, stop → re-derive root cause → escalate) | `0.35.0` |
| **Karpathy-skills · addyosmani/agent-skills · shanraisshan/claude-code-best-practice** | Rule presentation & context hygiene — quotable taglines, embedded self-checks, quantitative context guardrails | Presentation polish on 6 rules + quantitative guardrails in `context-engineering` (presentation only, count-neutral) | `0.36.0` |
| **[temporalio/skill-temporal-developer](https://github.com/temporalio/skill-temporal-developer)** | Temporal *fundamentals* — durable execution, determinism/replay, versioning, testing | `temporal-developer` collection skill (complements, not duplicates, `temporal-config-driven`) | `0.37.0` |
| **[wdm0006/python-skills](https://github.com/wdm0006/python-skills)** | Pre-add dependency evaluation; property-based testing | `library-review` core skill + a Property-Based Testing section in `test-driven-development` (rest skipped as redundant) | `0.38.0` |
| **[athola/claude-night-market](https://github.com/athola/claude-night-market)** (4-part audit) | Supply-chain defense; review grounding; escalation/safety/shell lenses; doc hygiene & resource-proportionality | `dependency-verification` · `safety-critical-patterns` · `shell-review` · `doc-consolidation` skills; finding-grounding in `code-review-and-quality`; tier-escalation + reversibility gates; `tool-design` §7 | `0.39.0`–`0.42.0` |
| **OpenTelemetry · W3C Trace Context · [Grafana Tempo](https://github.com/grafana/tempo)** | Vendor-neutral distributed tracing & trace↔log correlation | `otel-tracing` collection skill | `0.43.0` |
| **[Claude Code docs](https://code.claude.com)** | Verified token-economy settings | `autoCompactEnabled` / `maxSkillDescriptionChars` / terminal-title env in the generated settings, bounded SessionStart context hooks, and a leaner `templates/CLAUDE.md` | `0.44.0` |
| **[library-skills](https://library-skills.io)** | A dependency's *author-shipped, version-synced* skills as the defense against stale-API generation | Documented as the no-MCP companion to Context7 in `catalog/mcp.yaml`; referenced from `dependency-verification` & `library-review` | `0.45.0` |
| **[murphytrueman/design-system-ops](https://github.com/murphytrueman/design-system-ops)** | Operating a design system *over time* — token architecture, drift, health/maturity, governance, adoption, AI-readiness | `design-system-ops` collection skill (the operations layer, distinct from the build-time UI skills) | `0.46.0` |
| **[alibaba](https://github.com/alibaba) org review** (all 542 repos) | Staged leak-resistant evals; agent-operation authorization; tool-set orchestration + atomic state; agent-run span-tree instrumentation; live-attach debugging | `evals` §7, `agent-guardrails` §5, `tool-design` §8, `goal-setting-and-monitoring` §4, and live-attach debugging in `debugging-and-error-recovery` (from atrex-bench · open-agent-auth · app-controller · loongsuite-js · arthas) | `0.47.0` |
| **[alibaba/open-code-review](https://github.com/alibaba/open-code-review)** | Partition-for-coverage review — deterministic full-file coverage on large changesets, related-file bundling, plan-before-deep-pass | The "Cover Every Changed File" section in `code-review-and-quality` + a Coverage category in `sdlc-code-reviewer` | `0.48.0` |
| **[microsoft](https://github.com/microsoft) org review** (all 8,147 repos) | OWASP Agentic Top-10 (ASI01–ASI10) agent threats; agent-aware evals (multi-judge panels, multi-turn degradation, tool-vs-response grading); validator-in-the-loop + Medprompt prompting; sandbox policy schema & layered prompt-injection defense; approval-gate implementation; security-lint layer & SBOM; operationalized GenAI red-teaming; priority-based prompt pruning; quantified-lines PR sizing; first-party MCP servers | Extensions across `agent-guardrails` (ASI01–ASI10 + sandbox policy + injection layers), `evals` (§3 panels, §8 multi-turn), `reasoning-techniques`, `human-in-the-loop`, `linting-and-formatting`, `threat-model`, `security-and-hardening` (SBOM), `context-engineering`, `code-review-and-quality` + 4 MCP fragments (Azure · Azure DevOps · MS Learn · Wassette) — **0 new agents/skills/rules** (from agent-governance-toolkit · mxc · llmail-inject-challenge · lost_in_conversation · llm-as-judge · EvalsforAgentsInterop · promptbase · dsl-copilot · agents-humanoversight · PyRIT · eslint-plugin-sdl · sbom-tool · vscode-prompt-tsx · PullRequestQuantifier) | `0.50.0` |
| **[google](https://github.com/google) org review** (all 2,881 repos) | Reproducible-build verification & source-level missing-patch detection; secure-by-construction injection defense; archive-extraction & ReDoS hardening; multi-party authorization / breakglass; coverage-guided & continuous fuzzing; parameterized + semantic-equality + parallel/flaky testing; compile-time logic-bug & license-header lint layers + deterministic block sorting; multi-window burn-rate alerting & log rate-limiting; long-document extraction; prompt-as-code; statistical browser benchmarking; durable atomic writes; record-replay API testing; first-party SecOps MCP servers | Prose extensions across `security-and-hardening` (reproducible-build · missing-patch · secure-by-construction · archive · ReDoS), `human-in-the-loop` (MPA/breakglass), `testing` (fuzzing · parameterized · semantic-equality · parallel/flaky), `linting-and-formatting` (logic-bug + license-header layers · block sorting), `devops-observability` (burn-rate · log rate-limit), `context-engineering` (long-doc extraction), `reasoning-techniques` (prompt-as-code), `performance-optimization` (statistical benchmarking), `tool-design` (durable atomic writes), `api-integration` (record-replay) + **4 first-party SecOps MCP fragments** (Chronicle SIEM · GTI · SCC · SOAR) — **0 new agents/skills/rules** (from oss-rebuild · vanir · safe-active-record/mug · safearchive · re2 · building-secure-and-reliable-systems · patrick · go-cmp · atheris/honggfuzz/clusterfuzzlite · gtest-parallel · error-prone · addlicense · keep-sorted · prometheus-slo-burn · flogger · langextract · dotprompt · tachometer · renameio · test-server · mcp-security) | `0.51.0` |
| **[facebook](https://github.com/facebook) (Meta) org review** (all 168 repos) | Interprocedural taint / data-flow security analysis (source→sink across functions); continuous A/B performance-regression CI gate; defense-in-depth agent-sandbox enforcement (argument validation + OS-level backstop) | Prose extensions to `linting-and-formatting` (taint/data-flow layer), `devops-observability` (perf-regression gate), `agent-guardrails` (§4 layered sandbox enforcement) — **0 new agents/skills/rules** (from pyre-check/Pysa · mariana-trench · FAI-PEP · mcpguard-dynamic; the org is mostly libraries/frameworks, so the verify pass *dropped* the rest — `DNE-TaaC`, `mbt`, plus already-covered `infer`/`mariana-trench`-as-tool, `fbt`, `memlab`, …) | `0.52.0` |
| **[Netflix](https://github.com/Netflix) · [aws](https://github.com/aws) · [apple](https://github.com/apple) org review** (all **1,214** repos) | Service-level resilience the kit lacked entirely — stability patterns (timeout/retry-budget/circuit-breaker/bulkhead) + adaptive concurrency limiting, chaos engineering, and bounded-clock distributed time; failure-domain-aware progressive rollout; deterministic simulation testing; a formal RFC process (working-backwards + API bar-raiser); continuous usage-based least-privilege | The **new `resilience-engineering` rule** (chaos + stability patterns + bounded clocks, from `Netflix/concurrency-limits` · `Netflix/chaosmonkey` · `aws/clock-bound`); plus prose extensions to `devops-observability` (failure-domain rollout, from `aws/zone-aware-controllers-for-k8s`), `testing` (deterministic simulation testing, from `apple/foundationdb`), `spec-driven-development` (RFC track, from `aws/aws-cdk-rfcs`), and `security-and-hardening` (continuous least-privilege, from `Netflix/repokid`) — **1 new rule, 0 new agents/skills** (the orgs are overwhelmingly SDKs/CLIs/services, so the survey kept only 7 of 1,214) | `0.53.0` |

> Each adoption is detailed in the [CHANGELOG](../CHANGELOG.md) — including, for every review, what we
> deliberately **did not** add because the kit already covered it.

## The latest three reviews, in a bit more depth

**🔴 google org review → 21 hardening & testing patterns (0.51.0).** We reviewed **all 2,881 repos** in
the Google org (60 survey agents over every page → deep-dive the top ~300 candidates → adversarially
verify the shortlist). The vast majority — Android/Kotlin, C++ libraries, ML frameworks, language
runtimes, GCP product code — carried nothing transferable, and the verify pass *dropped* a third of the
shortlist: `deps.dev` (a REST/gRPC API, **not** an MCP server, despite the claim), `licensecheck`
(license *classification*, not the claimed compatibility gate), the Go/Rust/C++-locked tools
(`capslock`, `rust-crate-audits`, `fuzztest`, `libprotobuf-mutator` — can't be re-derived stack-agnostic),
`sqlcommenter` (archived → donated to OpenTelemetry), and `ax` (too early — "major breaking changes
prior to stable"). The survivors are **all prose extensions to existing files, zero new
agents/skills/rules**: reproducible-build verification, source-level missing-patch detection,
secure-by-construction injection defense, archive-extraction & ReDoS hardening in `security-and-hardening`;
multi-party authorization / breakglass in `human-in-the-loop`; coverage-guided & continuous fuzzing,
parameterized, semantic-equality, and parallel/flaky testing in `testing`; compile-time logic-bug &
license-header lint layers plus deterministic block sorting in `linting-and-formatting`; multi-window
burn-rate alerting & log rate-limiting in `devops-observability`; long-document extraction in
`context-engineering`; prompt-as-code in `reasoning-techniques`; statistical browser benchmarking in
`performance-optimization`; durable atomic writes in `tool-design`; record-replay API testing in
`api-integration`; and **4 first-party Google Security Operations MCP fragments** (Chronicle SIEM · GTI ·
SCC · SOAR).

**🔵 facebook (Meta) org review → 3 hardening & reliability patterns (0.52.0).** We reviewed **all 168
repos** in the Meta org (Meta long ago spun React, PyTorch, Jest, etc. into their own orgs, so the
`facebook` org is small). The org is almost entirely libraries, frameworks, and language tooling with
nothing transferable to a config scaffolder — and several famous repos were **already covered** (e.g.
`infer` by the 0.51 compile-time-logic-bug lint layer; React by the kit's React overlay; testing by an
already-deep `testing.md`). The verify pass *dropped* the weak picks: `DNE-TaaC` (datacenter
network-device testing, 1★, overlaps the config-driven skills) and `mbt` (a 0★ Meta-service-specific
binary-transparency client — that practice belongs to Sigstore/Certificate-Transparency, not this org).
Three genuine, stack-agnostic survivors, all **prose extensions, zero new agents/skills/rules**:
**interprocedural taint / data-flow analysis** (declare sources/sinks/sanitizers, trace untrusted data
across functions — distinct from single-line lint) in `linting-and-formatting` (from Pysa/`pyre-check` +
`mariana-trench`); a **continuous A/B performance-regression CI gate** (concurrent control vs treatment
to cancel environment noise, gate on the relative delta) in `devops-observability` (from `FAI-PEP`); and
**defense-in-depth agent-sandbox enforcement** (argument-validation layer + OS-level eBPF/seccomp backstop
*below* the existing declarative policy) in `agent-guardrails` §4 (from `mcpguard-dynamic`).

**⬛🟧 Netflix · aws · apple org review → resilience engineering & more (0.53.0).** We reviewed **all
1,214 repos** across the three orgs (34 survey agents over every page → deep-dive the candidates →
adversarially verify the shortlist). The orgs are overwhelmingly SDKs, CLIs, cloud-product code, and
running services — almost nothing transferable to a config scaffolder — and the verify pass scrutinized
each survivor against the live README + license. **Seven** genuine, stack-agnostic, permissively-licensed
disciplines survived. The biggest finding was a real **gap**: the kit had `agent-resilience` (the coding
agent's own retries) but **no service-level resilience rule at all**, so this review adds the kit's
**first new rule in many releases — `resilience-engineering`**: stability patterns
(timeout/retry-budget/circuit-breaker/bulkhead/load-shedding/fallback) + **adaptive concurrency limiting**
(TCP-congestion-control + Little's Law, from `Netflix/concurrency-limits`), **chaos engineering**
(steady-state hypothesis, blast-radius control, automated abort, from `Netflix/chaosmonkey`), and
**bounded-clock distributed time** (timestamps as `[earliest, latest]` + commit-wait, from
`aws/clock-bound`). The other four are prose extensions to existing files: **failure-domain-aware
progressive rollout** (one zone/region/cell at a time, exponential batches, reverse-order rollback) in
`devops-observability` (from `aws/zone-aware-controllers-for-k8s`); **deterministic simulation testing**
(single-seed control of all nondeterminism + in-sim fault injection) in `testing` (from
`apple/foundationdb`); a formal **RFC track** for one-way-door API changes (working-backwards artifacts +
API bar-raiser + staged sign-off) in `spec-driven-development` (from `aws/aws-cdk-rfcs`); and
**continuous, usage-based least-privilege** (audit exercised grants → auto-revoke the unused → versioned
rollback) in `security-and-hardening` (from `Netflix/repokid`).
