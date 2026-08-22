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
# SessionStart hook: surface the repo's active autonomy level so every session operates within it
# instead of forgetting the dial. The level is chosen at install time and recorded in the config
# snapshot; this just makes it visible each session. See AGENTS.md.
#
# Degrades to a no-op when jq isn't present or no level is recorded (never blocks startup).

OPTS="$ROOT/.ckit/config/init-options.json"

[ -f "$OPTS" ] || exit 0
command -v jq >/dev/null 2>&1 || exit 0

LEVEL=$(jq -r '.selection.autonomy // empty' "$OPTS" 2>/dev/null)
[ -n "$LEVEL" ] || exit 0

echo "## Active autonomy level: $LEVEL"
echo
echo "Operate within the \`$LEVEL\` autonomy level for this repo: it bounds how much you may do before a human acts. See AGENTS.md for what this level permits and what still needs human sign-off."

exit 0
