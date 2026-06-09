#!/usr/bin/env bash
# Stop hook: run the project's type checker, if it has one. Best-effort — NEVER blocks (exits 0).
# Detection: npm "typecheck" script, then tsconfig.json (tsc), then mypy (Python).
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$ROOT" 2>/dev/null || exit 0

out=""; ec=0

if [ -f package.json ] && command -v npm >/dev/null 2>&1 && grep -q '"typecheck"' package.json 2>/dev/null; then
  out="$(npm run -s typecheck 2>&1)"; ec=$?
elif [ -f tsconfig.json ] && command -v npx >/dev/null 2>&1; then
  out="$(npx --no-install tsc --noEmit 2>&1)"; ec=$?
elif command -v mypy >/dev/null 2>&1 && [ -f pyproject.toml ] && grep -q 'mypy' pyproject.toml 2>/dev/null; then
  out="$(mypy . 2>&1)"; ec=$?
fi

if [ "$ec" -ne 0 ] && [ -n "$out" ]; then
  echo "Type checker found issues — fix before finishing:"
  echo "$out" | tail -30
fi

exit 0
