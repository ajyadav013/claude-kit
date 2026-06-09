#!/usr/bin/env bash
# PreToolUse(Edit|Write): warn (never block) before editing security-sensitive surfaces —
# authentication, authorization, payments/billing, database migrations, infrastructure, or
# security controls. Advisory only (always exits 0); pairs with the autonomy + risk rules.
# Degrades to a no-op without jq or a recognisable file path.
command -v jq >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null || true)"
[ -z "$FILE_PATH" ] || [ "$FILE_PATH" = "null" ] && exit 0

low="$(printf '%s' "$FILE_PATH" | tr '[:upper:]' '[:lower:]')"

case "$low" in
  *auth*|*login*|*session*|*oauth*|*jwt*|*password*|*permission*|*rbac*|*authoriz*)
    echo "WARN: editing an AUTH / authorization surface ($FILE_PATH). High-risk: get review + security check before completion (.claude/rules/risk-classification.md)." >&2 ;;
esac
case "$low" in
  *payment*|*billing*|*invoice*|*checkout*|*stripe*|*charge*)
    echo "WARN: editing a PAYMENTS / billing surface ($FILE_PATH). High-risk: requires approval, test review, and rollback notes." >&2 ;;
esac
case "$low" in
  */migrations/*|*/migration/*|*alembic*|*_migration*|*.sql)
    echo "WARN: editing a DATABASE MIGRATION ($FILE_PATH). High-risk: confirm up + down paths and a rollback plan." >&2 ;;
esac
case "$low" in
  */.github/workflows/*|*/.gitlab-ci.yml|*terraform*|*.tf|*/helm/*|*/k8s/*|*/kubernetes/*|*/infra/*|*/deploy/*)
    echo "WARN: editing INFRASTRUCTURE / CI-CD ($FILE_PATH). High-risk: review blast radius and get approval." >&2 ;;
esac

exit 0
