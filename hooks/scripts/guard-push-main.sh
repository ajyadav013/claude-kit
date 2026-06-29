#!/usr/bin/env bash
# PreToolUse(Bash): BLOCK pushing to main/master from an agent session — use a feature branch + PR.
#
# Hardened against the naive `git<space>push` anchor that earlier inline guards used. It now:
#   - normalizes each ;|&-split segment, dropping a leading `git` plus any GLOBAL OPTIONS and their
#     value tokens, so `git -c k=v push origin main` / `git -C dir push origin main` cannot evade it;
#   - matches the branch token with a wider boundary so force-push refspecs are caught too:
#     `git push origin +main` (the '+' force prefix) and `git push origin HEAD:refs/heads/main`
#     (the '/' before main in a fully-qualified refspec).
# Legit branches that merely CONTAIN the substring are still spared (maintenance, main-feature,
# feature/main-ui, remaster-ui).
#
# Best-effort word-splitting — a guard, not a shell parser. Threat model: it stops accidental/agent
# pushes, not a determined operator deliberately crafting an obfuscated bypass (they own the machine
# and can disable the hook). Degrades to a no-op (fail-open) without jq.
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

PUSHLINES="$(printf '%s\n' "$NORM" | grep -E '^push([[:space:]]|$)' || true)"
if [ -n "$PUSHLINES" ] && printf '%s\n' "$PUSHLINES" | grep -qE '(^|[[:space:]:/+])(main|master)([[:space:]]|$)'; then
  echo "BLOCKED: refusing to push to main/master (incl. force-push refspecs like +main or HEAD:refs/heads/main, and 'git -c…'/'git -C…' forms) — use a feature branch and a PR." >&2
  exit 2
fi
exit 0
