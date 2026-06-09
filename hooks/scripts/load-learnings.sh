#!/bin/bash
# SessionStart hook: the "application" half of the self-improving learnings loop.
# 1. Injects the agent-memory learnings index into context so Claude applies
#    past learnings before new work.
# 2. Periodically nudges Claude to run the consolidate-learnings skill so the
#    knowledge base merges duplicates and stays lean.

MEM_DIR="$CLAUDE_PROJECT_DIR/.claude/agent-memory"
INDEX="$MEM_DIR/MEMORY.md"

[ -f "$INDEX" ] || exit 0

# Number of real learning entries in the index (lines like "- [Title](...)").
ENTRIES=$(grep -cE '^\s*- \[' "$INDEX" 2>/dev/null || echo 0)

# Nothing recorded yet -> stay silent.
[ "$ENTRIES" -gt 0 ] || exit 0

echo "## Accumulated learnings (from .claude/agent-memory/) — apply these before relevant work:"
echo
cat "$INDEX"
echo
echo "Before design or implementation, open the category file whose \"applies when\" matches the current task and follow it. New learnings are captured automatically; you may also use the /remember skill."

# --- Periodic consolidation trigger ---------------------------------------
# Increment a session counter; every CONSOLIDATE_EVERY sessions, nudge a merge pass.
COUNT_FILE="$MEM_DIR/.session-count"
CONSOLIDATE_EVERY=10

COUNT=$(cat "$COUNT_FILE" 2>/dev/null)
case "$COUNT" in (''|*[!0-9]*) COUNT=0;; esac
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNT_FILE" 2>/dev/null

if [ $((COUNT % CONSOLIDATE_EVERY)) -eq 0 ] && [ "$ENTRIES" -ge 4 ]; then
  echo
  echo "MAINTENANCE: It's been $CONSOLIDATE_EVERY sessions and there are $ENTRIES learnings. Run the \`consolidate-learnings\` skill to merge any duplicate/overlapping entries (do not delete distinct learnings)."
fi

exit 0
