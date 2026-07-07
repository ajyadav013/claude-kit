#!/usr/bin/env bash
# Stop hook: run the project's type checker, if it has one. Best-effort -- NEVER hard-blocks.
# Detection: npm "typecheck" script, then tsconfig.json (tsc), then mypy (Python).
#
# Feedback path (Claude Code >= 2.1.163): failures are returned as
# hookSpecificOutput.additionalContext JSON, which continues the turn as labeled "Stop hook
# feedback" so Claude reads the errors and fixes them before finishing -- bounded by the
# platform's 8-consecutive-continuation cap. On older versions the field is simply not read
# (same as the previous discard-to-debug-log behavior), so there is no downgrade risk.
# Per the hooks reference, stop_hook_active is checked so a stop chain gets ONE nudge --
# an unfixable failure (missing dep, broken env) cannot ping-pong the session.
set -u
if [ -t 0 ]; then INPUT=""; else INPUT="$(cat 2>/dev/null || true)"; fi
ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$ROOT" 2>/dev/null || exit 0

# Already continuing because of a stop hook -> stay quiet (one nudge per chain).
if command -v jq >/dev/null 2>&1; then
  ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || true)"
  [ "$ACTIVE" = "true" ] && exit 0
fi

out=""; ec=0

if [ -f package.json ] && command -v npm >/dev/null 2>&1 && grep -q '"typecheck"' package.json 2>/dev/null; then
  out="$(npm run -s typecheck 2>&1)"; ec=$?
elif [ -f tsconfig.json ] && command -v npx >/dev/null 2>&1; then
  out="$(npx --no-install tsc --noEmit 2>&1)"; ec=$?
elif command -v mypy >/dev/null 2>&1 && [ -f pyproject.toml ] && grep -q 'mypy' pyproject.toml 2>/dev/null; then
  out="$(mypy . 2>&1)"; ec=$?
fi

if [ "$ec" -ne 0 ] && [ -n "$out" ]; then
  MSG="Type checker found issues -- fix before finishing:
$(echo "$out" | tail -30)"
  if command -v jq >/dev/null 2>&1; then
    # stdout must be ONLY the JSON object for Claude Code to process it.
    jq -n --arg ctx "$MSG" '{hookSpecificOutput: {hookEventName: "Stop", additionalContext: $ctx}}'
  else
    echo "$MSG"  # no jq: legacy plain stdout (debug log only)
  fi
fi

exit 0
