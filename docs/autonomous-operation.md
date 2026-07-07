# Autonomous operation — running the kit unattended, safely

How to run a claude-kit project headlessly (`claude -p`), loop it with brakes, and map the kit's
autonomy levels onto Claude Code's real permission modes — grounded in what actually exists.

> **Grounding.** Every flag and mode below was verified against Claude Code **2.1.178**
> (`claude --help`) and the official permissions documentation in July 2026. CLI behavior drifts
> between releases — re-check `claude --help` before building automation on a flag.

The kit's autonomy posture is set by `.claude/rules/autonomy-levels.md`: the level is a **ceiling
chosen at install time**, `assisted` is the default, and the deterministic part is enforced by hooks
and `settings.permissions` — not by prompt text. This doc is about honoring that ceiling when no
human is watching.

## 1. Headless runs: `claude -p`

`claude -p "<prompt>"` prints the response and exits — the substrate for CI jobs, cron tasks, and
loops. Three properties change versus an interactive session, and all three matter for safety:

- **Nobody can answer a permission prompt.** Anything not pre-authorized (via
  `settings.permissions`, `--allowedTools`/`--disallowedTools`, or the permission mode) is denied
  rather than asked about. Headless autonomy is therefore *exactly* what you pre-authorize — no
  more, and silently no less.
- **The workspace trust dialog is skipped** (per the flag's own help text) — run `-p` only in
  directories you trust.
- **Settings files that fail validation are silently ignored** in print mode — a malformed
  `settings.json` means your permission rules and hooks *silently don't load*. Run
  `claude-kit validate` (or at minimum a JSON parse) in CI **before** the headless run, not after.

Flags worth knowing for unattended runs (all verified present): `--output-format json|stream-json`
and `--json-schema` for machine-readable results, `--max-budget-usd` as a hard per-run spend
ceiling, `--fallback-model` for overload resilience, `--session-id`/`--resume`/`--continue`/
`--fork-session` for session control, and `--settings`/`--setting-sources` to pin configuration.

> **No `--max-turns`.** The CLI (2.1.178) has no turn-cap flag — that's an Agent SDK feature. In
> shell automation, bound *iterations* yourself (§3) and bound *spend* with `--max-budget-usd`.

## 2. The `--bare` caveat: it strips the kit

`--bare` is real and useful — but its documented behavior is: *skip hooks, LSP, plugin sync,
attribution, auto-memory, background prefetches, keychain reads, and CLAUDE.md auto-discovery*.
For a claude-kit project that removes both delivery mechanisms at once:

- **No SessionStart context** — `load-continuity.sh` (working memory), `load-learnings.sh`
  (agent-memory), and `load-autonomy.sh` never fire, so the run *doesn't even know its autonomy
  level*.
- **No guard hooks** — `guard-push-main`, `guard-destructive-git`, `guard-secrets`,
  `warn-sensitive-files`, `warn-large-edits`, `warn-missing-tests`, `audit-log` (the very hooks the
  autonomous levels add to make autonomy safer) don't run.
- **No CLAUDE.md contract** — the project charter and its `.claude/rules/` pointers are not
  auto-discovered, so the engineering rules never enter context.

**Do not combine `--bare` with autonomous kit runs.** If you need bare's minimalism (cold-start
speed, no keychain access), the flag documents its own escape hatches — `--add-dir` re-includes
CLAUDE.md directories, `--append-system-prompt-file` re-injects a contract, `--settings` re-supplies
permissions — but you are then maintaining the guardrail set by hand, and the hooks stay off.
(`--safe-mode` is similar but broader — it disables all customizations for *troubleshooting a broken
config*; it is not an operating mode.)

## 3. A bounded loop: the "keep going" pattern, with brakes

The naive autonomous loop — `while :; do claude -p "keep going"; done` — fails two ways: no memory
between iterations, and no exit condition. The kit already ships both halves:

- **Memory:** `.claude/CONTINUITY.md` + the structured snapshot
  `.claude/state/pipeline-snapshot.json` (`last_gate_passed`, `lanes`, `next`). The resume contract
  is *reload, don't re-run* (`.claude/rules/continuity.md`): re-enter at the first gate after
  `last_gate_passed`, never re-apply committed work.
- **Exit condition:** the installed profile's gate tokens. Done = the profile's *final* gate is
  green (read your gate list from `.claude/config/stack-catalog.snapshot.yaml`; the orchestrator's
  Gate ↔ Stage Map defines the token order).

What the loop script must add is **brakes** — a hard iteration cap, a per-iteration spend cap, and
stall detection:

```bash
#!/usr/bin/env bash
# Bounded /sdlc loop. Brakes: iteration cap, per-run budget, stall detection.
set -u
MAX_ITER=8
FINAL_GATE="build-green"   # your profile's LAST gate token (see stack-catalog.snapshot.yaml)
SNAP=.claude/state/pipeline-snapshot.json
prev_gate=""

for i in $(seq 1 "$MAX_ITER"); do
  claude -p --permission-mode acceptEdits --max-budget-usd 5 \
    "Continue the /sdlc run per .claude/CONTINUITY.md. Re-enter at the first gate after
     last_gate_passed in $SNAP. Pass at most ONE more gate, update the snapshot, then stop."
  gate=$(sed -n 's/.*"last_gate_passed": *"\([^"]*\)".*/\1/p' "$SNAP" 2>/dev/null)
  [ "$gate" = "$FINAL_GATE" ] && { echo "pipeline complete: $gate"; exit 0; }
  if [ "$gate" = "$prev_gate" ]; then
    echo "STALLED at gate '${gate:-none}' — human review needed" >&2; exit 1
  fi
  prev_gate="$gate"
done
echo "iteration cap ($MAX_ITER) reached at gate '${prev_gate:-none}'" >&2
exit 1
```

Why each brake exists:

- **One gate per iteration** keeps each headless run small, cheap, and reviewable — and makes the
  snapshot token an honest progress meter.
- **The stall check** turns "quietly burning budget while rewriting state files" into a nonzero
  exit. A stall is the system asking for a human (`.claude/rules/agent-resilience.md`), not a
  reason to restart the loop with a bigger cap.
- **Nonzero exits are for humans.** The correct response to a stalled or capped loop is reading the
  transcript and the snapshot — never re-running with the brakes loosened.

> **Built-in alternative for "keep going until X":** Claude Code's `/goal` command is a native,
> session-scoped prompt-based Stop gate — it re-evaluates at every stop and keeps Claude working
> until the stated condition holds (the runtime caps consecutive stop-blocks at 8). For a single
> interactive session it replaces the loop above with zero configuration. The shell loop remains
> the right tool for headless runs, multi-session pipelines, and anywhere the brakes must live
> *outside* the model.

## 4. Mapping the kit's autonomy levels onto real permission modes

Verified `--permission-mode` choices (2.1.178): `acceptEdits` · `auto` · `bypassPermissions` ·
`manual` · `dontAsk` · `plan`. (`manual` is the CLI's name for the documented `default` mode —
prompt on first use of each tool. `auto` is a research preview that auto-approves with background
safety checks.)

| Kit level (`autonomy-levels.md`) | Permission mode | Notes |
|---|---|---|
| **advisory** | `plan` | Read-only exploration; matches "inspect, explain, plan, review". |
| **assisted** (default) | `manual` (`default`) | Prompt-per-action *is* the assisted posture. Not meaningful under `-p` — prompts can't be answered; stay interactive or pre-authorize narrowly. |
| **autonomous-local** | `acceptEdits` | Auto-accepts edits + common filesystem commands in the working dir. Keep push/PR denied in `settings.permissions`; `guard-push-main` independently blocks main/master pushes. `dontAsk` is the stricter alternative: deny-by-default with an explicit `permissions.allow` list. |
| **autonomous-pr** | `acceptEdits` + allow rules for branch/commit/push/PR-create | Merge stays denied — that's the level's definition, and it survives headless because denial is the default for anything un-allowed. |
| **enterprise-controlled** | managed (policy) settings + `audit-log` hook | Set `permissions.disableBypassPermissionsMode` (and `disableAutoMode`) in managed settings so nobody — including the agent's own session — can escalate past policy. |

**`bypassPermissions` maps to no kit level.** Its own documentation restricts it to isolated
environments (containers/VMs where Claude Code can't cause damage) — treat it as a sandbox tool,
not an autonomy setting. Even `autonomous-pr` doesn't need it: the level grants *specific* allow
rules, which is the opposite of skipping the permission system. `--allow-dangerously-skip-permissions`
only makes bypass *available*; it doesn't change this judgment.

## 5. Anti-gaming: what to watch in unattended logs

An unattended agent optimizing for "gates passed" can fake the meter instead of moving the work.
The kit's rules already define the defenses — these are the signs they exist to catch:

| Sign in the logs | What it means | The shipped defense |
|---|---|---|
| Gate token advanced but the gate's artifact (spec, review report, test output) is missing | The verdict may be asserted, not earned | `continuity.md` resume rule: a "passed" gate whose artifact is gone is **not passed** — verify before trust |
| "Tests pass" with no captured runner output | Fabricated/assumed verdict | `quality-gates.md` §2.5: a verdict must be backed by real, captured output; a fabricated one is an **auto-Critical** |
| Iterations that only rewrite `CONTINUITY.md`/state files, no code or test diffs | Progress theater | The §3 stall brake catches the unchanged token; also diff the repo between iterations (`git diff --stat`) |
| Review/security gates passing implausibly fast at high autonomy | Rubber-stamping | Blind review + Devil's Advocate protocol (`quality-gates.md`); sample-audit transcripts; `audit-log` (org autonomous levels) records an independent trail |
| Budget consumed, `last_gate_passed` unchanged | Runaway or thrash | `--max-budget-usd` bounds the damage; the loop exits nonzero; a human reads the transcript before any restart |

The general rule behind all five: **"Verify means run it, not imagine it"**
(`.claude/rules/rarv-cycle.md`), applied by someone the agent can't overrule — a hook, a loop
script, or you.

## Related

- `.claude/rules/autonomy-levels.md` — the ceiling and its five levels
- `.claude/rules/human-in-the-loop.md` · `.claude/rules/risk-classification.md` — when risk lowers the ceiling
- `.claude/rules/continuity.md` — the resume seam this doc's loop is built on
- `.claude/rules/agent-resilience.md` — crash/retry/stall handling inside a run
- [`docs/org-capabilities.md`](org-capabilities.md) — the org layer that selects autonomy levels at init
