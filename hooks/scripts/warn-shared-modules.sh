#!/usr/bin/env bash
# PreToolUse hook for Edit|Write: warn (never block) when touching project-wide / shared
# configuration whose change can ripple across the whole codebase. stdin: hook JSON.
# Always exits 0 so the edit is not blocked -- this is advisory only.
# Warnings return as hookSpecificOutput.additionalContext JSON on stdout (Claude reads it next to
# the tool result; PreToolUse support since CC 2.1.9). Without jq the warning falls back to stderr
# (debug-log only) -- same degradation as before.

[ -t 0 ] && exit 0  # no stdin (run by hand) -> no-op instead of blocking on `cat`
INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null || true)"

if [ -z "$FILE_PATH" ] || [ "$FILE_PATH" = "null" ]; then
  exit 0
fi

base="$(basename "$FILE_PATH")"

W=""
add() { W="${W:+$W
}$1"; }

# Project-wide build / dependency / config surfaces (any stack).
case "$base" in
  package.json|package-lock.json|pnpm-lock.yaml|yarn.lock| \
  pyproject.toml|poetry.lock|requirements.txt|requirements-*.txt|setup.cfg|setup.py| \
  go.mod|go.sum|Cargo.toml|Cargo.lock|Gemfile|Gemfile.lock|pom.xml|build.gradle| \
  tsconfig.json|tsconfig.*.json|*.config.js|*.config.ts|*.config.mjs|*.config.cjs| \
  Dockerfile|docker-compose.yml|docker-compose.*.yml|Makefile|CLAUDE.md)
    add "WARN: editing project-wide config: $FILE_PATH -- review cross-cutting impact and get approval if it affects others."
    ;;
esac

# Shared automation / kit configuration by path.
case "$FILE_PATH" in
  */.github/workflows/*|*/.gitlab-ci.yml|*azure-pipelines.yml|*/.claude/rules/*|*/.claude/settings*.json|*/.claude/agents/*)
    add "WARN: editing shared automation/config: $FILE_PATH -- review impact across the project."
    ;;
esac

if [ -n "$W" ]; then
  if command -v jq >/dev/null 2>&1; then
    # stdout must be ONLY the JSON object for Claude Code to process it.
    jq -n --arg ctx "$W" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}'
  else
    printf '%s\n' "$W" >&2 # no jq: legacy stderr (debug log only)
  fi
fi
exit 0
