#!/bin/bash
# PreToolUse(Bash): block git commits that would include secrets.
# Pairs with the secret-scanner agent and the protect-secrets read-guard -- this is the automatic,
# every-commit guardrail. Degrades to a no-op when not a git commit or git/jq is unavailable.
#
# Hardened against the `git<space>commit` anchor: each ;|&-split segment is normalized first, dropping
# a leading `git` plus any GLOBAL OPTIONS and their value tokens, so `git -c user.email=x commit` /
# `git -C dir commit` can't slip a secret-bearing commit past the guard. Best-effort word-splitting.
set -f
command -v jq >/dev/null 2>&1 || exit 0
CMD=$(jq -r '.tool_input.command // empty' 2>/dev/null || true)

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
      -*) shift ;; # any other global flag -> drop (conservative)
      *) break ;;  # first non-option token = the subcommand
    esac
  done
  [ "$#" -gt 0 ] && printf '%s\n' "$*"
}

NORM="$(printf '%s\n' "$CMD" | tr ';|&' '\n\n\n' | while IFS= read -r seg; do _norm_git_segment "$seg"; done)"
printf '%s\n' "$NORM" | grep -qE '^commit([[:space:]]|$)' || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
command -v git >/dev/null 2>&1 || exit 0

# 1) Secret-like files staged. Placeholder variants (.env.example/.sample/.template/.dist) are
#    spared -- they hold variable NAMES for onboarding, not values, and are committed on purpose
#    (same names-not-values philosophy as the content check below). POSIX ERE has no lookahead,
#    hence the second, negating grep.
BAD_FILES=$(git diff --cached --name-only 2>/dev/null \
  | grep -iE '(^|/)\.env($|\.)|\.(pem|key|p12|pfx)$|credentials?\.(json|ya?ml|md)$' \
  | grep -ivE '(^|/)\.env\.(example|sample|template|dist)$')

# 2) Secret-like VALUES in the staged diff (added lines only).
#    Detect real leaked-credential value shapes, NOT variable NAMES. Identifiers such as
#    SECRET_KEY, API_KEY, or *PASSWORD* are not themselves secrets -- flagging the names
#    false-positives on legitimate config/security documentation and code that merely
#    references env-var names or CI secret bindings. Actual leaked credentials are values.
#    The AWS secret key has no distinguishing prefix, so it is matched by its variable name
#    ADJACENT TO a 40-char value -- the pair is a value-shaped match, and the name alone (a CI
#    binding, a doc mention, a `<your-secret>` placeholder) still passes.
BAD_CONTENT=$(git diff --cached -U0 2>/dev/null \
  | grep -iE '^\+.*(-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|sk_live_[0-9a-zA-Z]{16,}|xox[baprs]-[0-9A-Za-z-]{10,}|gh[ps]_[0-9A-Za-z]{30,}|aws_secret_access_key[^0-9A-Za-z]{1,10}[0-9A-Za-z/+=]{40}([^0-9A-Za-z/+=]|$))')

# 3) Credentials embedded in a connection URI (scheme://user:secret@host) -- a VALUE shape, so it
#    is within the names-vs-values rule above, not against it. Only HIGH-ENTROPY passwords count:
#    real projects are full of `://user:pass@db` documentation placeholders (this repo ships 30+),
#    and a guard that blocks a compose-file example teaches people to bypass the guard. So require
#    >=16 chars, then drop the placeholder shapes. POSIX ERE has no lookahead, hence the second,
#    negating grep -- same idiom as the .env.example sparing above.
#    DELIBERATELY NOT COVERED, stated precisely because an earlier version of this comment
#    understated it (F-093): the `[a-z._-]+` alternative below is ENTROPY-BLIND. Any password made
#    only of letters, dots, underscores and hyphens passes, at any length -- a 32-character random
#    alphabetic string and a diceware passphrase both pass, while either one with a single digit
#    added is blocked. Passwords shorter than 16 chars never reach this grep at all; the `{16,}`
#    floor above already dropped them, so they are not what this carve-out is for.
#    Why it stays: the alternative is blocking `://user:passwordplaceholder@db`, and this repo
#    alone ships 30+ such lines. A guard that blocks documentation is one people route around, and
#    a bypassed guard catches nothing. Narrowing the class (a length bound, or requiring a
#    separator-free run) needs its own false-positive controls before it can ship.
#    The secret-scanner agent is the deeper, non-blocking net for this class.
BAD_URI=$(git diff --cached -U0 2>/dev/null \
  | grep -E '^\+.*://[^/:@[:space:]"]+:[^/:@[:space:]"]{16,}@' \
  | grep -ivE '://[^/:@[:space:]"]+:([a-z._-]+|<[^@]*>|\$\{[^@]*\}|\$[A-Za-z_]+|\*+|your[_a-z0-9]*|changeme[_a-z0-9]*|redacted|example[_a-z0-9]*)@')

BAD_CONTENT=$(printf '%s\n%s\n' "$BAD_CONTENT" "$BAD_URI" | grep -v '^[[:space:]]*$')

if [ -n "$BAD_FILES" ] || [ -n "$BAD_CONTENT" ]; then
  echo "BLOCKED: this commit appears to include secrets." >&2
  [ -n "$BAD_FILES" ] && { echo "  secret-like files staged:" >&2; echo "$BAD_FILES" | sed 's/^/    /' >&2; }
  [ -n "$BAD_CONTENT" ] && echo "  secret-like content staged -- move it to .env / a secret manager." >&2
  echo "  Unstage/rotate the secret, then retry. (guard-secrets.sh)" >&2
  exit 2
fi
exit 0
