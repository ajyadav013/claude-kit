# Seed Issues for Contributor Onboarding

This file contains ready-to-file "good first issue" drafts to seed the claude-kit issue tracker and help new contributors onboard. These issues are derived from the stack catalog's `status: planned` entries and follow the data-driven extension pattern outlined in [CONTRIBUTING.md](../../CONTRIBUTING.md).

## About These Issues

Each issue below is:

- **Real and scoped** — tied to a specific planned stack already listed in `catalog/stacks.yaml`
- **Data-driven** — requires no Python code changes; all work is catalog data and template content
- **Pattern-based** — follows the existing live overlay structure, so contributors copy and adapt rather than invent from scratch
- **Verifiable** — acceptance criteria are testable via `claude-kit validate`

## How to Add a Stack Overlay

Per [CONTRIBUTING.md](../../CONTRIBUTING.md) (the **Stack** bullet under "Adding components"):

1. **Complete the catalog entry** in `catalog/stacks.yaml` — remove `status: planned`, add `label`, `overlay_rules`, `overlay_agents` (optional, databases only), `skills` (optional), `stack_dir`, and `commands`.
2. **Create overlay content** under `templates/stacks/<stack_dir>/rules/<name>.md` (and `agents/` for databases). Copy an existing live overlay as your template: `templates/stacks/backend/go/net-http/` for a backend, `templates/stacks/frontend/react/` for a frontend.
3. **No Python changes** — `catalog.resolve()` must stay branch-free; this is a data change only.
4. **Test locally** — `pip install -e '.[dev]'`, then scaffold with the new stack and confirm it validates. There is no per-stack `init` flag; select the stack either interactively or with a `--config` YAML. For example, write `/tmp/vue.yaml` with:

   ```yaml
   frontend: { framework: vue, language: typescript }
   ```

   then run `claude-kit init /tmp/test --config /tmp/vue.yaml` and verify `claude-kit validate /tmp/test` passes.
5. **Update the matrix** (if applicable) — add a test case to the profile×stack self-test in `tests/test_catalog.py` if the new stack introduces a new dimension.

---

## Issue 1: Add Vue Stack Overlay (Frontend)

**Labels:** `good first issue`, `stack`, `help wanted`

### Context

Vue is a planned frontend stack (marked `status: planned` in `catalog/stacks.yaml`, line 40). The catalog entry exists with `stack_dir: frontend/vue` and a TypeScript/JavaScript language choice, but there is no overlay content yet, so it cannot be selected during `claude-kit init`.

To make Vue selectable, we need:

1. A completed catalog entry in `catalog/stacks.yaml` (remove `status: planned`, add `overlay_rules`, `skills`, and `commands`).
2. At least one overlay rule file under `templates/stacks/frontend/vue/rules/` that documents Vue-specific patterns (component architecture, data-fetching conventions, routing, state management, testing).

### Acceptance Criteria

- [ ] `catalog/stacks.yaml` entry for `vue` has `status: planned` removed and includes `overlay_rules`, `skills`, and `commands` (install, dev, test, lint, typecheck, build).
- [ ] `templates/stacks/frontend/vue/rules/vue-patterns.md` exists and documents the Vue stack conventions (follow the structure in `templates/stacks/frontend/react/rules/react-patterns.md` as a template).
- [ ] Scaffolding with the Vue stack selected (interactively, or via a `--config` YAML containing `frontend: { framework: vue }`) completes without error.
- [ ] `claude-kit validate` passes on the scaffolded project.
- [ ] If the profile×stack self-test in `tests/test_catalog.py` should cover Vue, add a test case (optional; can be a follow-up).

### Pointers

- **Existing overlay to copy from:** `templates/stacks/frontend/react/` (the structure and rule file are your template).
- **Files to modify:**
  - `catalog/stacks.yaml` (the `vue:` entry begins at line 38)
  - Create `templates/stacks/frontend/vue/rules/vue-patterns.md`

### Estimated Difficulty

Medium. Requires understanding the Vue ecosystem (Vue 3 Composition API, TypeScript, Vite, Vitest/Vue Test Utils, ESLint) and adapting the React patterns file. The catalog schema is straightforward; the rule-writing is the heavier lift.

---

## Issue 2: Add Svelte Stack Overlay (Frontend)

**Labels:** `good first issue`, `stack`, `help wanted`

### Context

Svelte is a planned frontend stack (marked `status: planned` in `catalog/stacks.yaml`, line 45). The catalog entry exists with `stack_dir: frontend/svelte` and a TypeScript language choice, but there is no overlay content yet, so it cannot be selected during `claude-kit init`.

To make Svelte selectable, we need:

1. A completed catalog entry in `catalog/stacks.yaml` (remove `status: planned`, add `overlay_rules`, `skills`, and `commands`).
2. At least one overlay rule file under `templates/stacks/frontend/svelte/rules/` that documents Svelte-specific patterns (component architecture, reactivity, stores, routing, testing with Vitest).

### Acceptance Criteria

- [ ] `catalog/stacks.yaml` entry for `svelte` has `status: planned` removed and includes `overlay_rules`, `skills`, and `commands` (install, dev, test, lint, typecheck, build).
- [ ] `templates/stacks/frontend/svelte/rules/svelte-patterns.md` exists and documents the Svelte stack conventions (follow the structure in `templates/stacks/frontend/react/rules/react-patterns.md` as a template).
- [ ] Scaffolding with the Svelte stack selected (interactively, or via a `--config` YAML containing `frontend: { framework: svelte }`) completes without error.
- [ ] `claude-kit validate` passes on the scaffolded project.

### Pointers

- **Existing overlay to copy from:** `templates/stacks/frontend/react/` (the structure and rule file are your template).
- **Files to modify:**
  - `catalog/stacks.yaml` (the `svelte:` entry begins at line 43)
  - Create `templates/stacks/frontend/svelte/rules/svelte-patterns.md`

### Estimated Difficulty

Medium. Requires understanding the Svelte ecosystem (Svelte 4/5, TypeScript, SvelteKit or Vite, Vitest, ESLint) and adapting the React patterns file. The catalog schema is straightforward; the rule-writing is the heavier lift.

---

## Issue 3: Add Django Stack Overlay (Backend, Python)

**Labels:** `good first issue`, `stack`, `help wanted`

### Context

Django is a planned backend framework for Python (marked `status: planned` in `catalog/stacks.yaml`, line 70). The catalog entry exists with `stack_dir: backend/python/django`, but there is no overlay content yet, so it cannot be selected during `claude-kit init`.

To make Django selectable, we need:

1. A completed catalog entry in `catalog/stacks.yaml` (remove `status: planned`, add `overlay_rules`, `skills`, and `commands`).
2. At least one overlay rule file under `templates/stacks/backend/python/django/rules/` that documents Django-specific patterns (project structure, apps, models, views/serializers, ORM, migrations, testing with pytest-django or the built-in test runner).

### Acceptance Criteria

- [ ] `catalog/stacks.yaml` entry for `django` has `status: planned` removed and includes `overlay_rules`, `skills`, and `commands` (install, dev, test, lint, migrate, etc.).
- [ ] `templates/stacks/backend/python/django/rules/django-patterns.md` exists and documents the Django stack conventions (follow the structure in `templates/stacks/backend/python/fastapi/rules/fastapi-patterns.md` or `templates/stacks/backend/go/net-http/rules/go-patterns.md` as templates).
- [ ] Scaffolding with the Django stack selected (interactively, or via a `--config` YAML containing `backend: { language: python, framework: django }`) completes without error.
- [ ] `claude-kit validate` passes on the scaffolded project.

### Pointers

- **Existing overlay to copy from:** `templates/stacks/backend/python/fastapi/` (same language) or `templates/stacks/backend/go/net-http/` (for the rule structure and layered-architecture sections).
- **Files to modify:**
  - `catalog/stacks.yaml` (the `django:` entry begins at line 68)
  - Create `templates/stacks/backend/python/django/rules/django-patterns.md`

### Estimated Difficulty

Medium. Requires understanding Django conventions (MTV architecture, ORM, class-based vs. function-based views, Django REST Framework for APIs, pytest-django) and adapting the FastAPI patterns file. The catalog schema is straightforward; the rule-writing is the heavier lift.

---

## Issue 4: Add Express Stack Overlay (Backend, Node.js)

**Labels:** `good first issue`, `stack`, `help wanted`

### Context

Express is a planned backend framework for Node.js (marked `status: planned` in `catalog/stacks.yaml`, line 79). The parent `node:` language entry is also marked `status: planned` (line 74). The catalog entry exists with `stack_dir: backend/node/express`, but there is no overlay content yet, so it cannot be selected during `claude-kit init`.

To make Express selectable, we need:

1. A completed catalog entry in `catalog/stacks.yaml` (remove `status: planned` from both the `node:` language and the `express:` framework, add `overlay_rules`, `skills`, and `commands`).
2. At least one overlay rule file under `templates/stacks/backend/node/express/rules/` that documents Express-specific patterns (router/middleware architecture, error handling, TypeScript setup, testing with Jest or Vitest, async/await patterns).

### Acceptance Criteria

- [ ] `catalog/stacks.yaml` entries for `node` and `express` have `status: planned` removed, and `express` includes `overlay_rules`, `skills`, and `commands` (install, dev, test, lint, typecheck, build).
- [ ] `templates/stacks/backend/node/express/rules/express-patterns.md` exists and documents the Express stack conventions (follow the structure in `templates/stacks/backend/python/fastapi/rules/fastapi-patterns.md` or `templates/stacks/backend/go/net-http/rules/go-patterns.md` as templates).
- [ ] Scaffolding with the Express stack selected (interactively, or via a `--config` YAML containing `backend: { language: node, framework: express }`) completes without error.
- [ ] `claude-kit validate` passes on the scaffolded project.

### Pointers

- **Existing overlay to copy from:** `templates/stacks/backend/go/net-http/` or `templates/stacks/backend/python/fastapi/` (for the rule structure and layered-architecture sections).
- **Files to modify:**
  - `catalog/stacks.yaml` (the `node:` language entry begins at line 72; the `express:` framework entry begins at line 77 — both need `status: planned` removed)
  - Create `templates/stacks/backend/node/express/rules/express-patterns.md`

### Estimated Difficulty

Medium. Requires understanding the Express/Node.js ecosystem (TypeScript, middleware composition, async error handling, Jest or Vitest for testing) and adapting the FastAPI or Go patterns file. The catalog schema is straightforward; the rule-writing is the heavier lift.

---

## Issue 5: Improve Catalog Validator — Add Duplicate-Skill Check

**Labels:** `good first issue`, `validator`, `help wanted`

### Context

The `claude-kit validate` CLI command (in `src/claude_kit/validator.py`) checks that a scaffolded project has a valid `.claude/` structure (required files present, YAML parses, referenced agents/skills/rules exist). The `check_catalog` function validates `catalog/*.yaml` internally (no orphan references, required fields present).

However, there is currently no check that prevents a skill from being listed multiple times in a single profile's `skills:` list. This can happen by accident when adding skills to `catalog/profiles.yaml` and leads to duplicate skill installations (harmless but wasteful).

We should add a validator check that scans each profile's `skills:` list and reports an error if any skill id appears more than once.

### Acceptance Criteria

- [ ] `src/claude_kit/validator.py` has a new function `check_duplicate_skills` (or add logic to the existing `check_catalog`).
- [ ] For each profile in `catalog/profiles.yaml`, if a skill id appears in `skills:` more than once, the validator raises an error like: `Profile 'standard' has duplicate skill 'api-integration' in skills list`.
- [ ] `pytest tests/test_validator.py` green, with a test case that triggers the duplicate-skill error.
- [ ] `python scripts/check_docs_consistency.py` and all other lints still pass.

### Pointers

- **File to modify:** `src/claude_kit/validator.py` (the `check_catalog` function or a new helper)
- **Test file:** `tests/test_validator.py` (add a test case with a profile YAML that has a duplicate skill)

### Estimated Difficulty

Easy. Straightforward Python logic: load the YAML, iterate each profile's `skills:` list, check for duplicates with a `set` or `Counter`. This is a good first issue for someone learning the claude-kit validation layer.

---

## Contributor Onboarding

If you are picking up one of these issues:

1. **Read [CONTRIBUTING.md](../../CONTRIBUTING.md)** — the "Adding components" section (the **Stack** bullet) is your recipe.
2. **Fork the repo** and create a branch for your issue.
3. **Test locally** with `pip install -e '.[dev]'` and `claude-kit init /tmp/test` (interactive, or with `--config` / `--defaults`).
4. **Run the full test suite** (`pytest`) and lints (`ruff check`, `mypy`, `shellcheck`, `python scripts/gen_hooks.py --check`, `python scripts/check_docs_consistency.py`) before opening a PR.
5. **Open a PR** with a clear description linking to this issue. CI must pass (tests, lints, the drift checks).

The maintainer ([@ajyadav013](https://github.com/ajyadav013)) will review and merge once green. Thanks for contributing to claude-kit.
