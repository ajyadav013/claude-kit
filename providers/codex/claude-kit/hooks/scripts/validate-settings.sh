#!/usr/bin/env bash
# PreToolUse: fail closed when a write would corrupt native hook JSON.
command -v jq >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"
case "$FILE_PATH" in
  */.codex/hooks.json|.codex/hooks.json) : ;;
  *) exit 0 ;;
esac
BODY="$(printf '%s' "$INPUT" | jq -r '.tool_input.content // empty' 2>/dev/null || true)"
[ -n "$BODY" ] || exit 0
if ! printf '%s' "$BODY" | jq empty >/dev/null 2>&1; then
  echo "BLOCKED: $FILE_PATH would not be valid JSON; invalid hook configuration disables guardrails." >&2
  exit 2
fi
exit 0
