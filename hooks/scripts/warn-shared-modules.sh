#!/usr/bin/env bash
# PreToolUse hook for Edit|Write: warn (never block) when touching project-wide / shared
# configuration whose change can ripple across the whole codebase. stdin: hook JSON.
# Always exits 0 so the edit is not blocked — this is advisory only.

INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null || true)"

if [ -z "$FILE_PATH" ] || [ "$FILE_PATH" = "null" ]; then
  exit 0
fi

base="$(basename "$FILE_PATH")"

# Project-wide build / dependency / config surfaces (any stack).
case "$base" in
  package.json|package-lock.json|pnpm-lock.yaml|yarn.lock| \
  pyproject.toml|poetry.lock|requirements.txt|requirements-*.txt|setup.cfg|setup.py| \
  go.mod|go.sum|Cargo.toml|Cargo.lock|Gemfile|Gemfile.lock|pom.xml|build.gradle| \
  tsconfig.json|tsconfig.*.json|*.config.js|*.config.ts|*.config.mjs|*.config.cjs| \
  Dockerfile|docker-compose.yml|docker-compose.*.yml|Makefile|CLAUDE.md)
    echo "WARN: editing project-wide config: $FILE_PATH — review cross-cutting impact and get approval if it affects others." >&2
    ;;
esac

# Shared automation / kit configuration by path.
case "$FILE_PATH" in
  */.github/workflows/*|*/.gitlab-ci.yml|*azure-pipelines.yml|*/.claude/rules/*|*/.claude/settings*.json|*/.claude/agents/*)
    echo "WARN: editing shared automation/config: $FILE_PATH — review impact across the project." >&2
    ;;
esac

exit 0
