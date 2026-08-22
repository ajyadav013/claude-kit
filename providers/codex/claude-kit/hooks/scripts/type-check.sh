#!/usr/bin/env bash
# Resolve the physical project root. Codex may launch hooks from a nested session cwd and does not
# guarantee CKIT_PROJECT_ROOT. Never follow provider-state/control symlinks while choosing a root.
_CKIT_ROOT_EXPLICIT=0
if [ -n "${CKIT_PROJECT_ROOT:-}" ]; then
  _CKIT_ROOT_START="$CKIT_PROJECT_ROOT"
  _CKIT_ROOT_EXPLICIT=1
else
  _CKIT_ROOT_START="$PWD"
fi
ROOT="$(cd -P -- "$_CKIT_ROOT_START" 2>/dev/null && pwd -P)" || exit 0
while :; do
  if [ -L "$ROOT/.ckit" ] || [ -L "$ROOT/.codex" ] || [ -L "$ROOT/.git" ] || \
     [ -L "$ROOT/.codex/hooks.json" ] || [ -L "$ROOT/.ckit/config" ] || \
     [ -L "$ROOT/.ckit/config/init-options.json" ]; then
    exit 0
  fi
  if { [ -d "$ROOT/.codex" ] && [ -f "$ROOT/.codex/hooks.json" ]; } || \
     { [ -d "$ROOT/.ckit/config" ] && [ -f "$ROOT/.ckit/config/init-options.json" ]; } || \
     [ -d "$ROOT/.git" ] || [ -f "$ROOT/.git" ]; then
    break
  fi
  [ "$_CKIT_ROOT_EXPLICIT" -eq 0 ] || exit 0
  [ "$ROOT" != "/" ] || exit 0
  ROOT="${ROOT%/*}"
  [ -n "$ROOT" ] || ROOT="/"
done
unset _CKIT_ROOT_EXPLICIT _CKIT_ROOT_START
# Stop hook: run the project's type checker, if it has one. Best-effort; requests at most one
# continuation when the checker proves an issue.
# Detection: npm "typecheck" script, then tsconfig.json (tsc), then mypy (Python).
#
# Feedback path: failures return top-level decision/reason JSON, which asks the host to continue
# the turn so the model reads the errors and fixes them before finishing.
# Per the hooks reference, stop_hook_active is checked so a stop chain gets ONE nudge --
# an unfixable failure (missing dep, broken env) cannot ping-pong the session.
set -u
if [ -t 0 ]; then INPUT=""; else INPUT="$(cat 2>/dev/null || true)"; fi
cd "$ROOT" 2>/dev/null || exit 0

# Already continuing because of a stop hook -> stay quiet (one nudge per chain).
if command -v jq >/dev/null 2>&1; then
  ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || true)"
  [ "$ACTIVE" = "true" ] && exit 0
fi

out=""; ec=0

if [ -f package.json ] && command -v npm >/dev/null 2>&1 && grep -q '"typecheck"' package.json 2>/dev/null; then
  out="$(npm run -s typecheck 2>&1)"; ec=$?
elif [ -f tsconfig.json ] && [ -x node_modules/.bin/tsc ] && command -v npx >/dev/null 2>&1; then
  # Gate on the local tsc binary: without it `npx --no-install` fails with toolchain noise
  # ("could not determine executable"), which would be fed to Codex as type errors. A repo with
  # tsconfig.json but no installed toolchain gets a silent skip -- missing deps are not type issues.
  out="$(npx --no-install tsc --noEmit 2>&1)"; ec=$?
elif command -v mypy >/dev/null 2>&1 && [ -f pyproject.toml ] && grep -q 'mypy' pyproject.toml 2>/dev/null; then
  out="$(mypy . 2>&1)"; ec=$?
fi

if [ "$ec" -ne 0 ] && [ -n "$out" ]; then
  MSG="Type checker found issues -- fix before finishing:
$(echo "$out" | tail -30)"
  if command -v jq >/dev/null 2>&1; then
    # stdout must be ONLY the JSON object for Codex to process it.
    jq -n --arg reason "$MSG" '{decision: "block", reason: $reason}'
  fi
fi

exit 0
