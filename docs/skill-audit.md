# Skill Surface Audit

## Overview

This document analyzes claude-kit's skill inventory — classification, sizing, per-profile footprint, and overlap — to inform future configuration decisions. It proposes no changes to `catalog/profiles.yaml`.

**Date:** 2026-07-03
**Version audited:** 0.57.0
**Total skills on disk:** 104 (56 core + 48 stack-collection)

---

## Method

Skills are classified by the presence of a `README.md` file in their directory:

- **CORE skills** — skill directory with NO `README.md`. Stack-agnostic capabilities.
- **STACK-COLLECTION skills** — skill directory WITH a `README.md`. Stack-specific or domain-specific add-ons (e.g., FastAPI patterns, React form patterns, PostgreSQL migrations).

This classification is exactly how `scripts/check_docs_consistency.py::_count_skills()` counts them. That function walks `skills/`, skips any entry that is not a directory or whose name starts with `_` (so the shared `_references/` support directory is not counted as a skill), and splits the rest on README presence. The expected split is pinned as anchors that CI checks against the docs:

- 56 core skills (no `README.md`).
- 48 stack-collection skills (with `README.md`).

Per-profile counts were measured on a `react + fastapi + postgres` project initialized with `--scope individual` for each profile (lean, standard, enterprise), by counting the files actually written under `.claude/`.

Token estimates are approximate, calculated as `total_bytes / 4`.

---

## Inventory

| Category | Count | Description |
|----------|-------|-------------|
| **Core skills** | 56 | Stack-agnostic capabilities (e.g., `sdlc`, `code-review-and-quality`, `test-driven-development`, `planning-and-task-breakdown`, `debugging-and-error-recovery`) |
| **Stack-collection skills** | 48 | Stack or domain-specific skills (e.g., `fastapi-service-patterns`, `react-hook-form-zod-patterns`, `alembic-migrations`, `kubectl-operations`) |
| **Total** | **104** | Full on-disk inventory (excludes the shared `_references/` support directory) |

The 48 collection skills are stack/domain add-ons. Note that `postgres-specialist`, `migration-specialist`, and `db-performance-reviewer` are DB-overlay **agents** (under `templates/stacks/db/postgres/agents/`), not skills — they are counted in the agent footprint below, not here.

---

## Per-Profile Install Footprint

Measured on a `react + fastapi + postgres` project with `--scope individual`:

| Profile | Agents | Skills | Rules | Approx. On-Disk Skill Tokens |
|---------|--------|--------|-------|-------------------------------|
| **lean** | 8 | 15 | 36 | ~46K |
| **standard** | 26 | 42 | 36 | ~121K |
| **enterprise** | 31 | 104 | 36 | ~895K |

**Notes:**

- Skill counts are skill *directories* (those containing a `SKILL.md`) — matching `_count_skills()` and the README's "What loads into your context" table. A raw `ls .claude/skills | wc -l` reads one higher (16 / 43 / 105) because each install also copies the shared `_references/` support directory, which is **not** a skill; `_count_skills()` deliberately excludes it. This is a counting convention, not duplicated content.
- Since the stack-true reclassification (0.58.1), the six frontend-specific skills (`frontend-ui-engineering`, `component-design`, `ui-ux-design`, `unit-test`, `api-integration`, `manual-test`) ride the React entry in `catalog/stacks.yaml` rather than the standard profile — a backend-only (`frontend: none`) standard install is six skills lighter. Lean gained one on the default stack (the react union now includes `manual-test` and `api-integration`; `api-integration` left the fastapi entry): 14 → 15.
- Agent counts exceed the raw profile agent list because the PostgreSQL DB overlay unions in 3 additional agents (`postgres-specialist`, `migration-specialist`, `db-performance-reviewer`).
- Rules are profile-independent: 25 core rules + 11 selected stack-overlay rules = 36 for all three profiles.
- Token estimates are approximate (bytes ÷ 4) and count on-disk **skill** bytes only, not always-resident context (see Finding below). The finding stands: enterprise installs every skill in the payload via `skills: all`.

---

## Finding: Enterprise Over-Install of Stack-Collection Skills

The enterprise profile uses `skills: all` in `catalog/profiles.yaml`, which installs **every skill in the payload** — including all 48 stack-collection skills, regardless of whether the project selected those stacks.

**Impact:**

- A `react + fastapi + postgres` project receives skills for stacks and domains it did not select (e.g., MongoDB, Kafka, Temporal, Kubernetes, GCP, and the planned Vue/Svelte/Django/Node collections' analogues) — roughly **895K tokens on disk** vs. standard's **~121K**.
- That is about **7× the on-disk skill footprint** of the standard profile. By skill count the ratio is smaller (104 vs 42, ~2.5×); the 7× gap is driven by size — collection skills carry a `README.md` plus more content per directory. Most of these files are irrelevant to the chosen stack.

**Important nuance (do not overstate):** Skills are **on-demand** (activated by context/user request), so this is **disk/selection bloat**, not always-resident context bloat. The harness does not load all skill files into every prompt. What it does do is:

1. Ship more files to disk than the selected stacks need.
2. Populate the skill selection pool with irrelevant options, which can add selection-time context depending on how the skill picker surfaces descriptions. Skill descriptions are already bounded by the `maxSkillDescriptionChars` setting (1100), so per-skill selection cost is capped, but a larger pool is still a larger pool.

---

## Overlap and Merge Candidates

The following skills are candidates for **review** (not deletion). They plausibly overlap in scope or could be consolidated; each needs a scope check before any action. All names below are claude-kit payload skills. Skills contributed by other installed plugins (e.g. `superpowers`, `frontend-design`) are out of scope for this audit and are not listed.

### Higher-priority review candidates

- `debugging-and-error-recovery` / `doubt-driven-development` — both touch error handling and recovery; scope may differ (recovery mechanics vs. a doubt-first development posture). Verify before merging.
- `planning-and-task-breakdown` / `task-tracker-sync` — both touch task planning; the latter looks like a narrower automation over the former.
- `docker-compose` / `docker-shared` / `dockerfile-backend` / `dockerfile-frontend` — four Docker-authoring skills; could be reviewed as a single containerization set. (These are stack-collection skills authored by the kit as reference material; the core payload itself remains Docker-optional.)
- `containerization-and-deployment` / `gcp-cloud-run-github-actions` — deployment-domain overlap; one generic, one GCP-specific.
- `observability-and-logging` / `otel-tracing` / `langfuse-llm-tracing` / `grafana-dashboards-and-alerts` — four observability skills; consider a documented hierarchy.

### Medium-priority review candidates

- `api-and-interface-design` / `graphql-patterns` / `api-pagination-filtering-sorting` — three API-design skills; the latter two are patterns under the first.
- `python-dao-and-database` / `alembic-migrations` — Python persistence skills; scope may overlap around schema/migration.
- `frontend-ui-engineering` / `radix-tailwind-component-patterns` / `react-hook-form-zod-patterns` — one general frontend skill plus two narrower pattern skills.
- `security-and-hardening` / `shannon-ai-pentest` / `zap-vapt-scanning` / `threat-model` / `safety-critical-patterns` — five security-domain skills; consider whether some are pattern sub-skills of `security-and-hardening`.

### Lower-priority review candidates

- `simplification-debt` / `over-engineering-review` / `code-simplification` — three simplification skills; scope may overlap or be intentionally layered (verify).
- `execute` / `incremental-implementation` — both relate to execution; one may be a narrower pattern.
- `remember` / `consolidate-learnings` — both touch memory/learning; verify the scope boundary.

**Candidates for review only. Delete nothing now.** Each entry needs an analysis of its unique value and usage before any merge or opt-in change.

---

## Recommendations

### Default (this audit takes)

**Leave `catalog/profiles.yaml` as-is and document the trade-off.**

- The enterprise profile installs all skills; that is a deliberate choice for organizations spanning many stacks. This audit does not overturn it.
- The on-demand activation model bounds the context cost of the extra files.
- Document the enterprise skill footprint in the profile description so the trade-off is visible before a user picks it.

### Optional (recommend evaluating, not implemented here)

**Evaluate a config-level opt-in that installs only stack-relevant collection skills.**

Potential approaches — all MUST stay `catalog/*.yaml` / config changes with NO `resolve()` branching (golden rule #6):

1. **Stack-aware skill filter** — a `skills: stack-relevant` option in `catalog/profiles.yaml` that installs the 56 core skills plus only the collection skills mapped to the selected stacks (via a mapping declared in `stacks.yaml`). For `react + fastapi + postgres`, that would be roughly a dozen-plus collection skills instead of 48. Footprint would fall well below the `skills: all` figure (exact size to be measured, not assumed).
2. **Explicit stack-skills opt-in** — a `--with-stacks <stack1,stack2>` selection (or interactive prompt) that augments the profile's skill list with only the named stack-collection skills.
3. **Enterprise variant** — an `enterprise-focused` profile that uses `skills: stack-relevant` instead of `skills: all`, for orgs that want enterprise agents/rules with a leaner skill footprint.

**Constraints:**

- Any solution stays a `catalog/profiles.yaml` or `catalog/stacks.yaml` data change.
- No stack-specific branching in `catalog.py::resolve()` (golden rule #6): the stack→skills mapping must be data in `stacks.yaml`, consumed by the existing resolver.
- The current `skills: all` enterprise profile stays available for multi-stack orgs.

**Next steps (if pursued):**

1. Measure the actual selection-time overhead of a 104-skill vs 42-skill install (do not assume it).
2. Prototype a `stack-relevant` mapping as pure data in `stacks.yaml`, resolved by the existing lookup.
3. Add the variant to `catalog/profiles.yaml` and measure the resulting footprint against the numbers above.

---

## Conclusion

- **Total skill inventory:** 104 (56 core + 48 stack-collection).
- **Enterprise over-install:** ~7× the on-disk skill footprint (~895K vs ~121K tokens) because `skills: all` installs cross-stack collection skills.
- **Risk level:** low for resident context (on-demand activation), but disk/selection bloat is measurable.
- **Action taken:** document the trade-off. Optionally evaluate a stack-relevant filter as a config-level change (no `resolve()` branching).

**No changes to `catalog/profiles.yaml` are made in this audit.**
