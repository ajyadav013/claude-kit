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

# Ensure the gitignored runtime state dir exists (the pip installer also creates it; this covers
# plugin context, where no scaffold step runs). The orchestrator writes pipeline-snapshot.json here.
mkdir -p "$MEM_DIR/state" 2>/dev/null || true

# Seed the live file from the template on first run (live file is gitignored).
if [ ! -f "$LIVE" ] && [ -f "$TEMPLATE" ]; then
  mkdir -p "$MEM_DIR" 2>/dev/null || true
  cp "$TEMPLATE" "$LIVE" 2>/dev/null || true
fi

[ -f "$LIVE" ] || exit 0

echo "## Working memory (.claude/CONTINUITY.md) — read before acting; write back before the turn ends:"
echo

# Bound the injected size. This file is dumped into context on EVERY session start, and a mature
# CONTINUITY.md can grow to tens of KB. Cap it to a digest that keeps BOTH ends — the top
# (Current Phase / Active Tasks) and the bottom (Next Steps / Blocked / Test-Build Status) — and trims
# only the middle (the unbounded Completed / Decisions / Modified-Files lists). The full file is always
# on disk; agents open it directly when they need the trimmed detail. Small files are emitted unchanged.
CAP=8000          # ~2,000 tokens
SIZE=$(wc -c <"$LIVE" 2>/dev/null || echo 0)
SIZE=${SIZE//[!0-9]/}
SIZE=${SIZE:-0}
if [ "$SIZE" -le "$CAP" ]; then
  cat "$LIVE"
else
  head -c 5500 "$LIVE"
  printf '\n\n...[middle of CONTINUITY.md trimmed to save context — %s bytes total; open .claude/CONTINUITY.md for the full working memory]...\n\n' "$SIZE"
  tail -c 2000 "$LIVE"
fi
echo
echo "Resume from \"Next Steps\". If you change phase or finish work, update CONTINUITY.md before ending the turn. Promote durable lessons to .claude/agent-memory/ via the remember skill."

exit 0
