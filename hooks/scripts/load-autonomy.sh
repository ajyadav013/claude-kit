#!/usr/bin/env bash
# SessionStart hook: surface the repo's active autonomy level so every session operates within it
# instead of forgetting the dial. The level is chosen at install time and recorded in the config
# snapshot; this just makes it visible each session. See .claude/rules/autonomy-levels.md.
#
# Degrades to a no-op when jq isn't present or no level is recorded (never blocks startup).

ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
OPTS="$ROOT/.claude/config/init-options.json"

[ -f "$OPTS" ] || exit 0
command -v jq >/dev/null 2>&1 || exit 0

LEVEL=$(jq -r '.selection.autonomy // empty' "$OPTS" 2>/dev/null)
[ -n "$LEVEL" ] || exit 0

echo "## Active autonomy level: $LEVEL"
echo
echo "Operate within the \`$LEVEL\` autonomy level for this repo: it bounds how much you may do before a human acts. See .claude/rules/autonomy-levels.md for what this level permits and what still needs human sign-off."

exit 0
