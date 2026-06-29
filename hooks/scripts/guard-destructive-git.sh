#!/usr/bin/env bash
# PreToolUse(Bash): BLOCK git commands that irreversibly destroy *uncommitted* work —
# `git reset --hard`, `git clean -f`, and worktree-wide discards (`git checkout/restore .`).
#
# Why a guard (block, exit 2) and not a warn: a PreToolUse advisory here would be theatre — the
# command would still run and the work would already be gone. So this guard refuses and points at
# the reversible alternative (`git stash`), exactly like guard-rm-rf points at trash. It completes
# the guard-rm-rf / guard-push-main destructive-command family with the single most common
# irreversible agent mistake: nuking its own uncommitted output.
#
# Hardened against the `git<space>subcommand` anchor: each ;|&-split segment is normalized first,
# dropping a leading `git` plus any GLOBAL OPTIONS and their value tokens, so a global option between
# `git` and the subcommand (`git -C dir reset --hard`, `git -c k=v clean -f`) cannot evade it.
#
# Scope is deliberately git-only and conservative — no false positives on `git clean -n` (dry run),
# plain branch checkouts, or single-file restores. Database wipes (`migrate reset`, `drop database`)
# stay OUT on purpose: they are legitimate in local dev, so blocking them would be over-reach; they
# are governed by .claude/rules/risk-classification.md and warn-sensitive-files on migration edits.
#
# Best-effort word-splitting — a guard, not a shell parser. Degrades to a no-op (fail-open) w/o jq.
set -f
command -v jq >/dev/null 2>&1 || exit 0
CMD="$(jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -z "$CMD" ] && exit 0

# Normalize one ;|&-split segment: if it is a git invocation, echo "<subcommand> <args...>" with the
# leading `git` and any global options (and their value tokens) stripped; echo nothing otherwise.
_norm_git_segment() {
  # shellcheck disable=SC2086  # intentional word-splitting of the segment into argv tokens
  set -- $1
  while [ "$#" -gt 0 ]; do
    case "$1" in
      sudo | command | builtin) shift ;;
      *=*) shift ;; # leading FOO=bar env assignment
      *) break ;;
    esac
  done
  case "${1:-}" in
    git | git.exe | */git | */git.exe) shift ;;
    *) return 0 ;;
  esac
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -C | -c | --git-dir | --work-tree | --namespace | --super-prefix)
        shift
        [ "$#" -gt 0 ] && shift
        ;;
      --git-dir=* | --work-tree=* | --namespace=* | --super-prefix=*) shift ;;
      --) shift; break ;;
      -*) shift ;; # any other global flag → drop (conservative)
      *) break ;;  # first non-option token = the subcommand
    esac
  done
  [ "$#" -gt 0 ] && printf '%s\n' "$*"
}

NORM="$(printf '%s\n' "$CMD" | tr ';|&' '\n\n\n' | while IFS= read -r seg; do _norm_git_segment "$seg"; done)"
[ -n "$NORM" ] || exit 0

# 1. reset --hard : discards all uncommitted tracked changes
if printf '%s\n' "$NORM" | grep -qE '^reset[[:space:]].*--hard'; then
  echo "BLOCKED: 'git reset --hard' discards uncommitted work irreversibly. Run 'git stash' to set it aside (recoverable via 'git stash list'), or 'git stash && git stash drop' to discard deliberately." >&2
  exit 2
fi

# 2. clean -f / --force : permanently deletes untracked files
if printf '%s\n' "$NORM" | grep -qE '^clean[[:space:]].*(-[a-zA-Z]*f|--force)'; then
  echo "BLOCKED: 'git clean -f' permanently deletes untracked files. Preview with 'git clean -n' first; to keep them, 'git stash -u'." >&2
  exit 2
fi

# 3. checkout/restore of the whole worktree ('.') : discards every unstaged change at once
if printf '%s\n' "$NORM" | grep -qE '^(checkout|restore)[[:space:]]+(.*[[:space:]])?\.([[:space:]]|$)'; then
  echo "BLOCKED: 'git checkout/restore .' discards every unstaged change in the worktree. Run 'git stash' first to keep a recoverable copy (restore a single file by naming it instead of '.')." >&2
  exit 2
fi

exit 0
