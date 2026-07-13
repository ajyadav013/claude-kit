#!/usr/bin/env bash
# PreToolUse(Edit|Write): warn (never block) before editing security-sensitive surfaces --
# authentication, authorization, payments/billing, database migrations, infrastructure, or
# security controls. Advisory only (always exits 0); pairs with the autonomy + risk rules.
# Degrades to a no-op without jq or a recognisable file path.
# Warnings return as hookSpecificOutput.additionalContext JSON on stdout (Claude reads it next to
# the tool result; PreToolUse support since CC 2.1.9) -- exit-0 stderr reaches the debug log only.
command -v jq >/dev/null 2>&1 || exit 0
[ -t 0 ] && exit 0  # no stdin (run by hand) -> no-op instead of blocking on `cat`
INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null || true)"
[ -z "$FILE_PATH" ] || [ "$FILE_PATH" = "null" ] && exit 0

low="$(printf '%s' "$FILE_PATH" | tr '[:upper:]' '[:lower:]')"

W=""
add() { W="${W:+$W
}$1"; }

case "$low" in
  *auth*|*login*|*session*|*jwt*|*password*|*permission*|*rbac*)
    add "WARN: editing an AUTH / authorization surface ($FILE_PATH). High-risk: get review + security check before completion (.claude/rules/risk-classification.md)." ;;
esac
case "$low" in
  *payment*|*billing*|*invoice*|*checkout*|*stripe*|*charge*)
    add "WARN: editing a PAYMENTS / billing surface ($FILE_PATH). High-risk: requires approval, test review, and rollback notes." ;;
esac
case "$low" in
  */migrations/*|*/migration/*|*alembic*|*_migration*|*.sql)
    add "WARN: editing a DATABASE MIGRATION ($FILE_PATH). High-risk: confirm up + down paths and a rollback plan." ;;
esac
case "$low" in
  */.github/workflows/*|*/.gitlab-ci.yml|*terraform*|*.tf|*/helm/*|*/k8s/*|*/kubernetes/*|*/infra/*|*/deploy/*)
    add "WARN: editing INFRASTRUCTURE / CI-CD ($FILE_PATH). High-risk: review blast radius and get approval." ;;
esac

if [ -n "$W" ]; then
  # stdout must be ONLY the JSON object for Claude Code to process it.
  jq -n --arg ctx "$W" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}'
fi
exit 0
