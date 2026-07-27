#!/usr/bin/env bash
# Persist a durable snapshot of ticket telemetry (tokens / model / agent / timing) -- NON-BLOCKING.
#
# `claude-kit tickets` reads the session transcript live, which is exactly what you want for the
# in-flight numbers. Transcripts are not forever, though: they live outside the repo under
# ~/.claude/projects/ and get pruned or lost with the machine. This Stop hook keeps a snapshot inside
# the project so the history survives that, and so pr-raiser has final figures to fold into the ticket
# at closure.
#
# The snapshot is produced by `claude-kit tickets --json` rather than re-derived here in jq. That
# matters: usage blocks repeat across streaming writes, so the totals are only correct if identical
# requestIds are collapsed before summing (a naive sum overstates output ~3.3x). Shelling out keeps
# exactly one implementation of that rule -- the tested Python one -- instead of a second, silently
# divergent copy in shell.
#
# Conservative + safe by construction:
#   * Silent no-op without the `claude-kit` CLI (plugin-only installs), without a ticket store, or
#     outside a project directory. Never fails a turn.
#   * Throttled: rewrites at most once per CLAUDE_KIT_TELEMETRY_INTERVAL seconds (default 60), so a
#     burst of short turns doesn't re-scan the transcript set every time.
#   * Detached background job -- the hook returns immediately and never delays the next prompt.
#   * Writes ONE gitignored path (.claude/state/), so it produces no commit noise.
#   * Metadata only: token counts, model ids, agent names, timestamps. No message content.
#   * Opt out with CLAUDE_KIT_NO_TELEMETRY=1.
set -u

[ -n "${CLAUDE_KIT_NO_TELEMETRY:-}" ] && exit 0
command -v jq >/dev/null 2>&1 || exit 0
command -v claude-kit >/dev/null 2>&1 || exit 0

INPUT=$(cat 2>/dev/null) || exit 0
PROJECT_DIR=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[ -n "$PROJECT_DIR" ] || PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"
[ -n "$PROJECT_DIR" ] && [ -d "$PROJECT_DIR" ] || exit 0

# No ticket store means nothing to attribute telemetry to.
[ -d "$PROJECT_DIR/docs/project/tickets" ] || exit 0

STATE_DIR="$PROJECT_DIR/.claude/state"
SNAPSHOT="$STATE_DIR/ticket-telemetry.json"

INTERVAL="${CLAUDE_KIT_TELEMETRY_INTERVAL:-60}"
case "$INTERVAL" in '' | *[!0-9]*) INTERVAL=60 ;; esac

# Throttle: skip when the existing snapshot is younger than the interval. `find -newermt` is not
# portable, so compare mtimes via stat, tolerating either BSD or GNU syntax.
if [ -f "$SNAPSHOT" ] && [ "$INTERVAL" -gt 0 ]; then
  MTIME=$(stat -f %m "$SNAPSHOT" 2>/dev/null || stat -c %Y "$SNAPSHOT" 2>/dev/null || echo 0)
  NOW=$(date +%s 2>/dev/null || echo 0)
  case "$MTIME$NOW" in
  *[!0-9]* | '') ;; # unreadable clock or mtime -- fall through and just write
  *)
    [ $((NOW - MTIME)) -lt "$INTERVAL" ] && exit 0
    ;;
  esac
fi

mkdir -p "$STATE_DIR" 2>/dev/null || exit 0

# Detached so the turn never waits on the scan. Write to a temp file and move into place, so a reader
# never observes a half-written snapshot.
(
  TMP="$SNAPSHOT.$$.tmp"
  if claude-kit tickets --path "$PROJECT_DIR" --json >"$TMP" 2>/dev/null; then
    mv -f "$TMP" "$SNAPSHOT" 2>/dev/null || rm -f "$TMP" 2>/dev/null
  else
    rm -f "$TMP" 2>/dev/null
  fi
) >/dev/null 2>&1 &

exit 0
