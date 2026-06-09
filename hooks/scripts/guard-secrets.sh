#!/bin/bash
# PreToolUse(Bash): block git commits that would include secrets.
# Pairs with the secret-scanner agent and the protect-secrets read-guard — this is the automatic,
# every-commit guardrail. Degrades to a no-op when not a git commit or git/jq is unavailable.
command -v jq >/dev/null 2>&1 || exit 0
CMD=$(jq -r '.tool_input.command // empty' 2>/dev/null)
echo "$CMD" | grep -qE 'git[[:space:]]+commit' || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
command -v git >/dev/null 2>&1 || exit 0

# 1) Secret-like files staged
BAD_FILES=$(git diff --cached --name-only 2>/dev/null \
  | grep -iE '(^|/)\.env($|\.)|\.(pem|key|p12|pfx)$|credentials?\.(json|ya?ml|md)$')

# 2) Secret-like content in the staged diff (added lines only)
BAD_CONTENT=$(git diff --cached -U0 2>/dev/null \
  | grep -iE '^\+.*(SECRET_KEY|API_KEY|PRIVATE KEY|AKIA[0-9A-Z]{16}|sk_live_[0-9a-zA-Z]{16,}|xox[baprs]-[0-9A-Za-z-]+|gh[ps]_[0-9A-Za-z]{30,}|[A-Za-z0-9_]*PASSWORD[A-Za-z0-9_]*[[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"']+)')

if [ -n "$BAD_FILES" ] || [ -n "$BAD_CONTENT" ]; then
  echo "BLOCKED: this commit appears to include secrets." >&2
  [ -n "$BAD_FILES" ] && { echo "  secret-like files staged:" >&2; echo "$BAD_FILES" | sed 's/^/    /' >&2; }
  [ -n "$BAD_CONTENT" ] && echo "  secret-like content staged — move it to .env / a secret manager." >&2
  echo "  Unstage/rotate the secret, then retry. (guard-secrets.sh)" >&2
  exit 2
fi
exit 0
