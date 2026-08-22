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
# Stop hook: if the session changed files but never wrote back to CONTINUITY.md, say so.
#
# This is the missing half of a pair. load-continuity.sh READS working memory at SessionStart and
# is measurably load-bearing; nothing ever WROTE it back, so `AGENTS.md` step 4
# ("Update CONTINUITY.md with what passed") and `AGENTS.md` were promises with no
# mechanism behind them -- observed 0/12 across every arm, including the arm where rarv-cycle was
# the ONLY rule loaded. A rule that never fires is not a weak rule, it is an unkept contract; the
# fix is a mechanism, not louder prose.
#
# The signal is mtime ordering, not "was CONTINUITY.md touched". A file can be touched by the
# SessionStart seed or by an unrelated tool. What the rule actually asks for is a write-back AFTER
# the work, so the hook asks exactly that: is CONTINUITY.md older than the newest change? Anything
# else would credit a stale file as a write-back.
#
# Deliberately NOT graded here: whether the CONTINUITY.md content is any good. That is an LLM
# judgement, and this kit's own rules forbid treating one as a deterministic oracle. The hook
# checks the one thing that is mechanically decidable -- that a write-back happened after the work.
#
# On a proven violation this asks the host to continue once so the model can write back continuity.
# Every unknown degrades to silence: no git, no jq, no working tree, unreadable mtimes. A hook that
# guesses would produce exactly the false accusation it exists to prevent. ``stop_hook_active``
# below is the host-provided loop guard that prevents a second continuation request.
set -u
if [ -t 0 ]; then INPUT=""; else INPUT="$(cat 2>/dev/null || true)"; fi
cd "$ROOT" 2>/dev/null || exit 0

# One nudge per stop chain, per the hooks reference: a session that cannot satisfy the check
# (read-only checkout, no CONTINUITY.md template) must not ping-pong against it.
if command -v jq >/dev/null 2>&1; then
  ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || true)"
  [ "$ACTIVE" = "true" ] && exit 0
fi

command -v git >/dev/null 2>&1 || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

LIVE="$ROOT/.ckit/CONTINUITY.md"

# Portable mtime. GNU `-c %Y` MUST be tried first: on GNU coreutils `-f` selects *filesystem*
# status and `%m` yields the mount point, so a BSD-first chain SUCCEEDS on Linux with a nonsense
# value and silently disables the check. Any non-numeric result is treated as unknown.
mtime() {
  m=$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo "")
  case "$m" in *[!0-9]* | "") echo "" ;; *) echo "$m" ;; esac
}

# Changed files the session is answerable for. Kit runtime state is excluded: CONTINUITY.md itself
# lives under .ckit/, and counting it as "work" would make the hook trigger on its own output.
CHANGED="$(git status --porcelain 2>/dev/null | awk '{print $NF}' | grep -vE '^(\.ckit|\.ckit)/' || true)"
[ -n "$CHANGED" ] || exit 0

COUNT="$(printf '%s\n' "$CHANGED" | wc -l | tr -d ' ')"

if [ ! -f "$LIVE" ]; then
  REASON="no .ckit/CONTINUITY.md exists, so this session's state was never recorded"
else
  CM="$(mtime "$LIVE")"
  [ -n "$CM" ] || exit 0 # unreadable mtime: unknown, not a violation
  NEWEST=0
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    fm="$(mtime "$f")"
    [ -n "$fm" ] || continue
    [ "$fm" -gt "$NEWEST" ] && NEWEST="$fm"
  done <<EOF
$CHANGED
EOF
  [ "$NEWEST" -gt 0 ] || exit 0        # nothing datable: unknown, not a violation
  [ "$CM" -ge "$NEWEST" ] && exit 0    # written back after the work -- the rule was followed
  REASON="CONTINUITY.md was last written before the newest of those changes"
fi

MSG="RARV step 4 (Verify) is not complete: $COUNT changed file(s), but $REASON.

Before finishing, update .ckit/CONTINUITY.md with: what you changed, what you VERIFIED and the
real command output that proves it, and the next step. Per AGENTS.md an uncited
PASS is treated as fabricated -- if you could not run the checks, record that instead of a verdict.

Changed:
$(printf '%s\n' "$CHANGED" | head -20)"

if command -v jq >/dev/null 2>&1; then
  # stdout must be ONLY the JSON object for Codex to process it.
  jq -n --arg reason "$MSG" '{decision: "block", reason: $reason}'
fi

exit 0
