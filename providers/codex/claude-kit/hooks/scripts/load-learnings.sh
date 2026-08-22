#!/bin/bash
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
# SessionStart hook: the "application" half of the self-improving learnings loop.
# 1. Injects the agent-memory learnings index into context so Codex applies
#    past learnings before new work.
# 2. Periodically nudges Codex to run the consolidate-learnings skill so the
#    knowledge base merges duplicates and stays lean.

MEM_DIR="$ROOT/.ckit/agent-memory"
INDEX="$MEM_DIR/MEMORY.md"

[ -f "$INDEX" ] || exit 0

# Number of real learning entries in the index (lines like "- [Title](...)").
# grep -c prints "0" and exits 1 when there are no matches, so guard with `|| true` -- NOT `|| echo 0`,
# which would append a second line and make the integer test below fail with "integer expected".
ENTRIES=$(grep -cE '^\s*- \[' "$INDEX" 2>/dev/null || true)
ENTRIES=${ENTRIES:-0}

# Nothing recorded yet -> stay silent.
[ "$ENTRIES" -gt 0 ] || exit 0

echo "## Accumulated learnings (from .ckit/agent-memory/) -- apply these before relevant work:"
echo

# Bound the injected index. It is dumped into context on EVERY session start and grows with each
# learning; cap it so an aged repo's index can't quietly become a per-session tax. The full index is
# always on disk (.ckit/agent-memory/MEMORY.md); the consolidation nudge below keeps it lean.
CAP=8000          # ~2,000 tokens
ISIZE=$(wc -c <"$INDEX" 2>/dev/null || echo 0)
ISIZE=${ISIZE//[!0-9]/}
ISIZE=${ISIZE:-0}
if [ "$ISIZE" -le "$CAP" ]; then
  cat "$INDEX"
else
  head -c "$CAP" "$INDEX"
  printf '\n\n...[learnings index trimmed to save context -- %s bytes total; open .ckit/agent-memory/MEMORY.md for the full index]...\n' "$ISIZE"
fi
echo
# Whether capture actually runs is the init-time `capture_mode` choice, and since 0.76.0 the default
# is OFF (background capture spawns a a provider background task job that reads transcript content, so it is consent-
# gated). This line used to promise "captured automatically" unconditionally; in a default install
# that is false, and an agent told its learnings are already being recorded has no reason to record
# them — a plausible part of why writing a learning was never observed in any measured session.
CAPTURE_NOTE="Automatic capture is unsupported on this provider; use the explicit \$remember skill for durable learnings."
echo "Before design or implementation, open the category file whose \"applies when\" matches the current task and follow it. $CAPTURE_NOTE"

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
