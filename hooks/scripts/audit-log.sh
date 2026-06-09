#!/usr/bin/env bash
# PostToolUse(all tools): append a one-line local audit record (timestamp · tool · target) to
# .claude/state/audit.log for organization / enterprise-controlled mode. LOCAL ONLY — it never sends
# anything anywhere, never reads file contents, and always exits 0 (it must not affect the tool).
# Degrades to a no-op without jq. The log lives under the gitignored .claude/state/ dir.
command -v jq >/dev/null 2>&1 || exit 0
INPUT="$(cat)"

TOOL="$(echo "$INPUT" | jq -r '.tool_name // "?"' 2>/dev/null || echo '?')"
TARGET="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.command // empty' 2>/dev/null || true)"
# Keep the record short and never include file bodies.
TARGET="$(printf '%s' "$TARGET" | tr '\n' ' ' | cut -c1-120)"

DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/state"
mkdir -p "$DIR" 2>/dev/null || exit 0
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo '?')"
printf '%s\t%s\t%s\n' "$TS" "$TOOL" "$TARGET" >>"$DIR/audit.log" 2>/dev/null || true
exit 0
