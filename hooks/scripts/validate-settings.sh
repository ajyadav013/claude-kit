#!/usr/bin/env bash
# PreToolUse(Write): block a write to .claude/settings.json (or settings.local.json) that is not valid
# JSON — a malformed settings file silently disables every hook, so this is a deterministic, low-noise
# guard (exit 2 only on a genuine parse failure of a settings write). Degrades to a no-op without jq
# or for any other path.
command -v jq >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"
case "$FILE_PATH" in
  */.claude/settings.json|*/.claude/settings.local.json|.claude/settings.json|.claude/settings.local.json) : ;;
  *) exit 0 ;;
esac

BODY="$(echo "$INPUT" | jq -r '.tool_input.content // empty' 2>/dev/null || true)"
[ -z "$BODY" ] || [ "$BODY" = "null" ] && exit 0

if ! printf '%s' "$BODY" | jq empty >/dev/null 2>&1; then
  echo "BLOCKED: $FILE_PATH would not be valid JSON. Fix the syntax — invalid settings.json disables all hooks. (validate-settings.sh)" >&2
  exit 2
fi
exit 0
