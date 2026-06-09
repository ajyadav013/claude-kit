#!/usr/bin/env bash
# SessionStart hook: surface working memory (CONTINUITY.md) into context so the session resumes
# exactly where the previous one left off — across token limits and context compaction.
#
# Pairs with load-learnings.sh: CONTINUITY = ephemeral current-task state,
# agent-memory = durable learnings. See .claude/rules/continuity.md.

ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
MEM_DIR="$ROOT/.claude"
LIVE="$MEM_DIR/CONTINUITY.md"
TEMPLATE="$MEM_DIR/CONTINUITY.template.md"

# Fallback to the kit-bundled template when running as a plugin and the project has none yet.
if [ ! -f "$TEMPLATE" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "$CLAUDE_PLUGIN_ROOT/templates/CONTINUITY.template.md" ]; then
  TEMPLATE="$CLAUDE_PLUGIN_ROOT/templates/CONTINUITY.template.md"
fi

# Seed the live file from the template on first run (live file is gitignored).
if [ ! -f "$LIVE" ] && [ -f "$TEMPLATE" ]; then
  mkdir -p "$MEM_DIR" 2>/dev/null || true
  cp "$TEMPLATE" "$LIVE" 2>/dev/null || true
fi

[ -f "$LIVE" ] || exit 0

echo "## Working memory (.claude/CONTINUITY.md) — read before acting; write back before the turn ends:"
echo
cat "$LIVE"
echo
echo "Resume from \"Next Steps\". If you change phase or finish work, update CONTINUITY.md before ending the turn. Promote durable lessons to .claude/agent-memory/ via the remember skill."

exit 0
