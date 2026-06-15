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
# Scope is deliberately git-only and conservative — no false positives on `git clean -n` (dry run),
# plain branch checkouts, or single-file restores. Database wipes (`migrate reset`, `drop database`)
# stay OUT on purpose: they are legitimate in local dev, so blocking them would be over-reach; they
# are governed by .claude/rules/risk-classification.md and warn-sensitive-files on migration edits.
#
# Degrades to a no-op (fail-open) without jq.
command -v jq >/dev/null 2>&1 || exit 0
CMD="$(jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -z "$CMD" ] && exit 0

# 1. reset --hard : discards all uncommitted tracked changes
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+reset[[:space:]].*--hard'; then
  echo "BLOCKED: 'git reset --hard' discards uncommitted work irreversibly. Run 'git stash' to set it aside (recoverable via 'git stash list'), or 'git stash && git stash drop' to discard deliberately." >&2
  exit 2
fi

# 2. clean -f / --force : permanently deletes untracked files
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+clean[[:space:]].*(-[a-zA-Z]*f|--force)'; then
  echo "BLOCKED: 'git clean -f' permanently deletes untracked files. Preview with 'git clean -n' first; to keep them, 'git stash -u'." >&2
  exit 2
fi

# 3. checkout/restore of the whole worktree ('.') : discards every unstaged change at once
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+(checkout|restore)[[:space:]]+(.*[[:space:]])?\.([[:space:]]|$)'; then
  echo "BLOCKED: 'git checkout/restore .' discards every unstaged change in the worktree. Run 'git stash' first to keep a recoverable copy (restore a single file by naming it instead of '.')." >&2
  exit 2
fi

exit 0
