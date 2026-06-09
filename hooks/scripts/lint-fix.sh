#!/usr/bin/env bash
# Stop hook: auto-fix lint/format issues using whatever tooling the project already has.
# Stack-detecting and best-effort — NEVER blocks (always exits 0). No-op if no tooling is found.
# Detection order: an npm "lint" script, ruff (Python), gofmt (Go), cargo fmt (Rust).
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$ROOT" 2>/dev/null || exit 0

out=""

# JavaScript / TypeScript — only if the project defines a "lint" script
if [ -f package.json ] && command -v npm >/dev/null 2>&1 && grep -q '"lint"' package.json 2>/dev/null; then
  out="$(npm run -s lint --if-present 2>&1)"
fi

# Python — ruff (fix + format) if available
if command -v ruff >/dev/null 2>&1 && { [ -f pyproject.toml ] || [ -f ruff.toml ] || ls ./*.py >/dev/null 2>&1; }; then
  ruff check --fix --quiet . 2>/dev/null || true
  ruff format --quiet . 2>/dev/null || true
fi

# Go
if [ -f go.mod ] && command -v gofmt >/dev/null 2>&1; then
  gofmt -w . 2>/dev/null || true
fi

# Rust
if [ -f Cargo.toml ] && command -v cargo >/dev/null 2>&1; then
  cargo fmt 2>/dev/null || true
fi

# Surface unresolved lint problems back to Claude so it can fix them.
if [ -n "${out:-}" ] && echo "$out" | grep -qiE 'error|warning|problem'; then
  echo "Linter reported issues — fix before finishing:"
  echo "$out" | tail -30
fi

exit 0
