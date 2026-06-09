#!/usr/bin/env bash
# PreToolUse(Write): when writing an agent (.claude/agents/*.md) or skill (.../skills/*/SKILL.md),
# check the YAML frontmatter carries the fields Claude Code needs (agents: name + description;
# skills: description). Advisory only (always exits 0) — it warns so a malformed component is caught
# before it silently fails to auto-discover, without blocking iterative authoring.
# Degrades to a no-op without jq or for non-agent/skill paths.
command -v jq >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"
[ -z "$FILE_PATH" ] || [ "$FILE_PATH" = "null" ] && exit 0

case "$FILE_PATH" in
  */agents/*.md) KIND="agent" ;;
  */skills/*/SKILL.md) KIND="skill" ;;
  *) exit 0 ;;
esac

BODY="$(echo "$INPUT" | jq -r '.tool_input.content // empty' 2>/dev/null || true)"
[ -z "$BODY" ] || [ "$BODY" = "null" ] && exit 0

# Frontmatter must open with '---' on the first line.
case "$BODY" in
  ---*) : ;;
  *) echo "WARN: $KIND $FILE_PATH has no YAML frontmatter (expected a leading '---' block)." >&2; exit 0 ;;
esac

FM="$(printf '%s\n' "$BODY" | awk 'NR==1&&/^---/{f=1;next} f&&/^---/{exit} f{print}')"
printf '%s\n' "$FM" | grep -qE '^description:[[:space:]]*\S' \
  || echo "WARN: $KIND $FILE_PATH frontmatter is missing 'description:' (needed for auto-selection)." >&2
if [ "$KIND" = "agent" ]; then
  printf '%s\n' "$FM" | grep -qE '^name:[[:space:]]*\S' \
    || echo "WARN: agent $FILE_PATH frontmatter is missing 'name:'." >&2
fi
exit 0
