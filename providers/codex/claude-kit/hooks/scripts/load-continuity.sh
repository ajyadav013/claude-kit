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
# SessionStart hook: surface working memory (CONTINUITY.md) into context so the session resumes
# exactly where the previous one left off -- across token limits and context compaction.
#
# Pairs with load-learnings.sh: CONTINUITY = ephemeral current-task state,
# agent-memory = durable learnings. See AGENTS.md.

MEM_DIR="$ROOT/.ckit"
LIVE="$MEM_DIR/CONTINUITY.md"
TEMPLATE="$MEM_DIR/CONTINUITY.template.md"

# Fallback to the kit-bundled template when running as a plugin and the project has none yet.
if [ ! -f "$TEMPLATE" ] && [ -n "${PLUGIN_ROOT:-}" ] && [ -f "$PLUGIN_ROOT/templates/CONTINUITY.template.md" ]; then
  TEMPLATE="$PLUGIN_ROOT/templates/CONTINUITY.template.md"
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

# Staleness check: a live file untouched for 7+ days is historical context, not a current plan.
# Portable mtime: GNU stat first (-c fails on BSD/darwin), BSD stat as fallback; any failure or
# non-numeric result degrades to "fresh" (no warning) -- advisory only, never a hard failure.
NOW=$(date +%s 2>/dev/null || echo 0)
MTIME=$(stat -c %Y "$LIVE" 2>/dev/null || stat -f %m "$LIVE" 2>/dev/null || echo "")
case "$MTIME" in *[!0-9]* | "") MTIME=$NOW ;; esac
AGE_DAYS=$(((NOW - MTIME) / 86400))

echo "## Working memory (.ckit/CONTINUITY.md) -- read before acting; write back before the turn ends:"
echo
if [ "$AGE_DAYS" -ge 7 ]; then
  printf '> WARNING: CONTINUITY.md was last written %s days ago -- treat it as historical context. Verify against git log/git status (and upstream currency) before resuming from its Next Steps.\n\n' "$AGE_DAYS"
fi

# Bound the injected size. This file is dumped into context on EVERY session start, and a mature
# CONTINUITY.md can grow to tens of KB. Cap it to a digest that keeps BOTH ends -- the top
# (Current Phase / Active Tasks) and the bottom (Next Steps / Blocked / Test-Build Status) -- and trims
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
  printf '\n\n...[middle of CONTINUITY.md trimmed to save context -- %s bytes total, over the %s-byte budget; open .ckit/CONTINUITY.md for the full working memory, then rotate completed detail to .ckit/state/continuity-archive.md per AGENTS.md]...\n\n' "$SIZE" "$CAP"
  tail -c 2000 "$LIVE"
fi
echo
echo "Resume from \"Next Steps\". If you change phase or finish work, update CONTINUITY.md before ending the turn. Keep the live file under ~8,000 bytes -- rotate completed-phase detail to .ckit/state/continuity-archive.md. Promote durable lessons to .ckit/agent-memory/ via the remember skill."

exit 0
