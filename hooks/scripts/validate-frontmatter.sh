#!/usr/bin/env bash
# PreToolUse(Write): when writing an agent (.claude/agents/*.md) or skill (.../skills/*/SKILL.md),
# check the YAML frontmatter carries the fields Claude Code needs (agents: name + description;
# skills: description). Advisory only (always exits 0) -- it warns so a malformed component is caught
# before it silently fails to auto-discover, without blocking iterative authoring.
# Degrades to a no-op without jq or for non-agent/skill paths.
# Warnings return as hookSpecificOutput.additionalContext JSON on stdout (Claude reads it next to
# the tool result; PreToolUse support since CC 2.1.9) -- exit-0 stderr is debug-log-only.
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

W=""
add() { W="${W:+$W
}$1"; }

# Frontmatter must open with '---' on the first line.
case "$BODY" in
  ---*)
    FM="$(printf '%s\n' "$BODY" | awk 'NR==1&&/^---/{f=1;next} f&&/^---/{exit} f{print}')"
    printf '%s\n' "$FM" | grep -qE '^description:[[:space:]]*\S' \
      || add "WARN: $KIND $FILE_PATH frontmatter is missing 'description:' (needed for auto-selection)."
    if [ "$KIND" = "agent" ]; then
      printf '%s\n' "$FM" | grep -qE '^name:[[:space:]]*\S' \
        || add "WARN: agent $FILE_PATH frontmatter is missing 'name:'."
    fi
    ;;
  *) add "WARN: $KIND $FILE_PATH has no YAML frontmatter (expected a leading '---' block)." ;;
esac

if [ -n "$W" ]; then
  # stdout must be ONLY the JSON object for Claude Code to process it.
  jq -n --arg ctx "$W" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}'
fi
exit 0
