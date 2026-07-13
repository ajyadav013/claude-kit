#!/usr/bin/env bash
# PreToolUse(Edit|Write): warn (never block) when a single edit is large enough that it should have a
# written plan / spec first. Advisory only (always exits 0). Heuristic by changed-line count; a hook
# cannot see whether a plan exists, so it nudges rather than enforces.
# Degrades to a no-op without jq. Threshold overridable via CLAUDE_LARGE_EDIT_LINES.
#
# Feedback path: the warning is returned as hookSpecificOutput.additionalContext JSON on stdout,
# which Claude reads next to the tool result (PreToolUse support since Claude Code 2.1.9; on a
# tool-call failure the context was dropped before 2.1.110). Exit-0 stderr goes to the debug log
# only per the hooks reference, so plain stderr is kept solely as the no-jq fallback.
command -v jq >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
THRESHOLD="${CLAUDE_LARGE_EDIT_LINES:-150}"

# Write -> whole new file content; Edit -> the replacement text; MultiEdit -> all edits joined.
BODY="$(echo "$INPUT" | jq -r '
  .tool_input.content
  // .tool_input.new_string
  // ([.tool_input.edits[]?.new_string] | join("\n"))
  // empty' 2>/dev/null || true)"
[ -z "$BODY" ] || [ "$BODY" = "null" ] && exit 0

LINES="$(printf '%s\n' "$BODY" | wc -l | tr -d ' ')"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"

if [ "$LINES" -gt "$THRESHOLD" ]; then
  W="WARN: large edit (~$LINES lines) to ${FILE_PATH:-this file}. Write/confirm a plan or spec first and split into reviewable steps (.claude/rules/mandatory-workflow.md, no-large-unreviewed-edits)."
  # stdout must be ONLY the JSON object for Claude Code to process it.
  jq -n --arg ctx "$W" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}'
fi
exit 0
