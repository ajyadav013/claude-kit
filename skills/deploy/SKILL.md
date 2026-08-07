---
name: deploy
description: Deploy-and-verify loop — commit, trigger the deployment, watch the pipeline, verify the running instances, test, fix, repeat until clean. Interviews you once for your delivery setup. Use when asked to deploy, ship, or run the ship loop.
argument-hint: '<commit message | "commit-only" | "no-deploy" | "setup" | "loop">'
---

# deploy — commit → deploy → monitor → verify → repeat

A delivery-execution skill for projects where deployment is driven from the repo (a tag, a
branch push, a CI dispatch, or a deploy command). It runs once by default, or loops
autonomously until the exit condition is met. It is deliberately **configuration-driven**:
nothing below assumes a specific CI provider, orchestrator, or cloud.

| Usage | What it does |
|-------|-------------|
| `/deploy` | Commit + push (+ merge to the integration branch) + trigger the deployment |
| `/deploy fix: use internal URL` | Same, with a custom commit description |
| `/deploy commit-only` | Commit + push only — no merge, no deploy |
| `/deploy no-deploy` | Commit + push + merge, skip the deploy trigger |
| `/deploy setup` | (Re-)run the interview and rewrite `.claude/config/deploy.yaml` |
| `/deploy loop` | Full ship loop: implement → commit → deploy → monitor → verify → test → repeat |

---

## Step 0 — Load or build the delivery profile

Read `.claude/config/deploy.yaml`. If it exists, use it and **ask nothing** already answered.
If it is missing (or `setup` mode), build it: **auto-detect first, ask only what detection
can't settle**, then write the file so the interview never repeats.

### What to detect / ask

1. **Integration branch** — the branch deployments are cut from (staging/SIT/release), if any.
   Detect: a branch named in `CLAUDE.md`, or the branch recent merge commits target. Trunk-based
   projects answer "none — deploy from the default branch"; record that explicitly.
2. **Commit message format** — detect from `git log --oneline -15` (a consistent prefix pattern
   is the answer). Else ask, offering: Conventional Commits (`fix: …`), ticket-prefixed
   (`PROJ-1234: …`), or a custom template with placeholders (e.g.
   `ID:<ticket>; DONE:<pct>; HOURS:<n>; <description>`). Also ask for any required trailer.
   Once configured, the format is **byte-exact, every commit** — no drift, no improvisation.
3. **Deploy trigger** — how a deployment actually starts. One of:
   - **tag push** — capture the exact tag format (e.g. `vX.Y.Z`, `deploy-<env>-<n>`) and the
     remote it must be pushed to;
   - **merge/push to a branch** — the deploy happens on push; nothing extra to run;
   - **CI manual dispatch** — capture the exact command (e.g. the CI CLI's run/dispatch call);
   - **a deploy command or script** — capture it verbatim, including arguments (many platforms
     wrap tagging in a helper; treat the helper as the trigger and don't second-guess it).
4. **Pipeline monitor** — how to watch the build/deploy pipeline. Offer, in order of preference:
   - the CI provider's **CLI** (e.g. `gh run watch` for GitHub Actions, `glab ci status` for
     GitLab, the Azure DevOps CLI for Azure Pipelines) — poll-able, scriptable;
   - a **provider MCP server**, if one is connected — use its build-status tools;
   - a **web dashboard URL** watched through the browser (Chrome DevTools MCP) when no CLI/API
     is available — capture the URL;
   - **none** — the user watches and reports back; the loop pauses at this step.
5. **Runtime verification** — how to confirm the new version is actually live and healthy.
   Ask which of these the project has (multiple allowed; capture the exact command, context,
   and namespace/identifier for each — these run **read-only, every iteration**):
   - **Kubernetes**: `kubectl rollout status <deployment>` then `kubectl get pods` (with the
     configured `--context`/`-n`); `kubectl logs` for spot checks;
   - **container runtime / compose**: the equivalent `ps`/service-status listing;
   - **cloud service CLI**: the provider's service/revision describe command (ECS/Cloud Run/
     App Service and equivalents);
   - **PaaS CLI**: the platform's status command (fly/heroku/railway and equivalents);
   - **HTTP**: a health/readiness endpoint, and ideally a **version endpoint** that reports the
     deployed SHA/tag — the strongest single check;
   - **logs/monitoring**: an error-rate or log query to compare before/after.
6. **Test surface** — a URL to exercise in the browser after deploy (optional; skip if none).
7. **Exit condition & bounds** — when the loop stops. Default: pipeline green **and** instances
   healthy on the new revision **and** zero blocking/major findings. Default cap: 5 iterations;
   3-strike rule below always applies.

Write the answers to `.claude/config/deploy.yaml` (create `.claude/config/` if needed):

```yaml
integration_branch: <name or "none">
commit_format:
  template: "<the exact template>"
  trailer: "<required trailer or omit>"
deploy:
  trigger: tag | branch-push | ci-dispatch | command
  detail: "<tag format / command verbatim>"
pipeline:
  monitor: ci-cli | mcp | browser | manual
  detail: "<command / URL>"
verify:
  - "<read-only command 1>"
  - "<read-only command 2>"
test_url: "<URL or omit>"
loop:
  max_iterations: 5
```

**Never store secrets or tokens in this file** — commands reference environment variables;
the file is committed config, not a credential store. Record the active run's state (tag,
build id, findings) in `.claude/CONTINUITY.md`, not here.

---

## Non-negotiable rules (every iteration)

- **The commit format is law.** Use the configured template byte-exactly, every commit,
  including merge commits and fix-up iterations.
- **Stage by name.** `git add <path>` for the files you changed — never `git add -A`. Never
  stage `.env`, credentials, OS junk, or large binaries.
- **Never force-push. Never deploy from the default branch** unless the config explicitly says
  the project is trunk-based. Never skip the configured merge step.
- **Never auto-resolve merge conflicts** — show the conflicting files and ask.
- **Verification commands are read-only.** Status, list, describe, logs — never delete,
  restart, or scale anything while verifying (the kit's guard hooks block destructive
  orchestrator commands regardless).
- **A release that carries a database migration pauses for explicit human confirmation** with a
  written rollback note before the trigger fires (see `.claude/rules/risk-classification.md`).
- **No success without evidence.** "Deployed" means: the pipeline reports success, the runtime
  checks show the **new** revision healthy, and — where possible — a unique marker from your
  diff is observably live (a version endpoint, a log line, a visible change). An image tag or
  a green build alone proves nothing on shared branches.
- **3-strike stop.** If the same failure survives 3 iterations with no forward progress, STOP,
  keep the environment as-is, and escalate with the evidence collected.
- **Stash before switching.** `git stash --include-untracked` if the tree is dirty before any
  checkout; pop when switching back.
- **One deploy trigger per iteration.** Don't re-fire the trigger while a pipeline for the
  previous one is still running.

---

## The flow

### 1. Implement (loop mode only)
Make the smallest coherent change toward the goal, matching the codebase's conventions. For
non-trivial feature work, run it through `/sdlc` first and use this skill for the delivery
tail. In non-loop mode, skip — the user already made their changes.

### 2. Local checks (loop mode only)
Run what the repo has — linter → type-check → build → unit tests — and get them green before
anything ships. A red local check never proceeds to commit.

### 3. Commit
`git status -s` → if changes exist: `git diff --stat` to understand them, use `$ARGUMENTS` as
the description when provided (and not a mode keyword), else write one from the diff. Stage by
name, commit in the configured format, push to the feature branch. No changes → say so and
continue. **`commit-only` mode stops here.**

### 4. Merge to the integration branch (when configured)
Skip when `integration_branch: none`. Otherwise: confirm there are new commits to merge
(`git log <integration>..<feature> --oneline` — nothing new → say so and stop), then stash if
dirty → checkout → pull → merge the feature branch (merge commit in the configured format) →
push. Conflicts → stop and ask. **`no-deploy` mode stops after this step.**

### 5. Trigger the deployment
Fire the configured trigger exactly as recorded (push the tag in the configured format, or run
the configured command verbatim). Don't add a second confirmation layer on top of the user's
permission settings — Claude Code already gates tool execution. If the trigger command isn't
found in this shell, tell the user the exact line to run themselves.

### 6. Monitor the pipeline (~60s cadence)
Watch via the configured monitor until it reports success or failure. On **failure**: pull the
build/deploy logs through the same channel, root-cause, and go back to step 1 with the fix —
never re-fire the trigger without a change. If the monitor is `manual`, hand the user the
URL/command and wait for their report.

### 7. Verify the runtime
Run every configured `verify:` command. Confirm the **new** revision is what's serving:
rollout complete, instances Ready/healthy, and the version endpoint / diff marker matches this
iteration's change. Partial rollouts, crash-looping instances, or a stale version = failure →
collect evidence → back to step 1.

### 8. Test (loop mode only)
If a `test_url` is configured, exercise it in the browser (Chrome DevTools MCP when available):
the change renders and behaves correctly · network calls return expected status/payloads with
no 5xx · zero new console errors · surrounding features still work. Record each finding:
severity (blocking/major/minor) · what · where · repro · expected.

### 9. Decide
Switch back to the feature branch (pop the stash if one was made).
- **Non-loop mode** → done. Report what was deployed, with the evidence.
- **Loop mode** → exit condition met → STOP and report: what shipped, trigger reference
  (tag/build id), runtime status, and the test log. Otherwise the findings become the worklist
  → go to step 1. The 3-strike rule and the iteration cap always win over "one more try".

---

## Batching (loop mode)

For a large worklist, group related fixes into coherent deployable batches — deploy and verify
each batch before starting the next. Split any batch that mixes low-risk polish with a risky
change; the risky change ships alone, with its own verification.

## Working memory

Checkpoint `.claude/CONTINUITY.md` at every stage transition — config in use, iteration number,
trigger reference, pipeline result, runtime evidence, findings — so the loop survives context
compaction and a fresh session can resume exactly where it stopped (see
`.claude/rules/continuity.md`).

## What this skill never does

Provision infrastructure · merge to a production branch that requires human review · run
destructive runtime commands · bypass the profile's quality gates for the code itself. It
executes an **existing, human-designed delivery path** and verifies the result — it does not
invent one. If the project has no delivery path yet, that's `/ci-cd-and-automation` and
`/shipping-and-launch` territory first.
