#!/usr/bin/env bash
# PostToolUse(Edit|Write): after a source-code change, remind that tests should accompany it.
# Advisory only (always exits 0). Stays quiet for test files, docs, config, and the .claude/ config
# itself. A per-event hook can't track the whole change set, so it nudges on production-code edits.
# Degrades to a no-op without jq.
# The reminder returns as hookSpecificOutput.additionalContext JSON on stdout (Claude reads it next
# to the tool result, per the current hooks reference) -- exit-0 stderr is debug-log-only.
command -v jq >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null || true)"
[ -z "$FILE_PATH" ] || [ "$FILE_PATH" = "null" ] && exit 0

low="$(printf '%s' "$FILE_PATH" | tr '[:upper:]' '[:lower:]')"

# Skip non-source: tests, docs, config, markdown, and the kit's own config.
case "$low" in
  *test*|*spec*|*.md|*.markdown|*.json|*.ya?ml|*.toml|*.ini|*.cfg|*.txt|*.lock|*/.claude/*)
    exit 0 ;;
esac

# Only nudge for recognisable source files.
case "$low" in
  *.py|*.ts|*.tsx|*.js|*.jsx|*.go|*.rs|*.rb|*.java|*.kt|*.cs|*.php|*.swift|*.scala|*.c|*.cc|*.cpp|*.h|*.hpp)
    W="REMINDER: code changed ($FILE_PATH) -- add or update tests before marking work complete (.claude/rules/testing.md)."
    # stdout must be ONLY the JSON object for Claude Code to process it.
    jq -n --arg ctx "$W" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}' ;;
esac
exit 0
