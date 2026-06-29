#!/usr/bin/env bash
# Stop hook: auto-fix lint/format issues using whatever tooling the project already has.
# Stack-detecting and best-effort — NEVER blocks (always exits 0). No-op if no tooling is found.
#
# Scope (P0-3): by DEFAULT only the files changed in this repo are formatted, so a Stop never rewrites
# files the user never touched. Set CLAUDE_KIT_AUTOFIX=1 to restore whole-repo formatting. When git is
# unavailable or this isn't a work tree, it falls back to whole-repo (best-effort).
# Tools: ruff (Python), gofmt/rustfmt (Go/Rust), and an npm "lint" script (JS/TS).
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$ROOT" 2>/dev/null || exit 0

out=""

# Whole-repo only when explicitly opted in, or when we can't scope via git.
SCOPED=1
[ "${CLAUDE_KIT_AUTOFIX:-0}" = "1" ] && SCOPED=0
if [ "$SCOPED" = 1 ] && ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  SCOPED=0
fi

# Collect changed files once (tracked modifications vs HEAD + new untracked), NUL-safe. read -d '' is
# portable back to bash 3.2 (macOS), unlike `mapfile -d`.
py=() go=() rs=() js=()
if [ "$SCOPED" = 1 ]; then
  while IFS= read -r -d '' f; do
    [ -f "$f" ] || continue
    case "$f" in
      *.py) py+=("$f") ;;
      *.go) go+=("$f") ;;
      *.rs) rs+=("$f") ;;
      *.js | *.jsx | *.ts | *.tsx | *.mjs | *.cjs) js+=("$f") ;;
    esac
  done < <(
    {
      git diff --name-only -z HEAD 2>/dev/null
      git ls-files --others --exclude-standard -z 2>/dev/null
    }
  )
fi

# JavaScript / TypeScript — the project's own "lint" script (can't be scoped per-file generically, so
# in scoped mode run it only when JS/TS actually changed).
if [ -f package.json ] && command -v npm >/dev/null 2>&1 && grep -q '"lint"' package.json 2>/dev/null; then
  if [ "$SCOPED" = 0 ] || [ "${#js[@]}" -gt 0 ]; then
    out="$(npm run -s lint --if-present 2>&1)"
  fi
fi

# Python — ruff (fix + format)
if command -v ruff >/dev/null 2>&1; then
  if [ "$SCOPED" = 1 ]; then
    if [ "${#py[@]}" -gt 0 ]; then
      ruff check --fix --quiet "${py[@]}" 2>/dev/null || true
      ruff format --quiet "${py[@]}" 2>/dev/null || true
    fi
  elif [ -f pyproject.toml ] || [ -f ruff.toml ] || ls ./*.py >/dev/null 2>&1; then
    ruff check --fix --quiet . 2>/dev/null || true
    ruff format --quiet . 2>/dev/null || true
  fi
fi

# Go
if command -v gofmt >/dev/null 2>&1; then
  if [ "$SCOPED" = 1 ]; then
    [ "${#go[@]}" -gt 0 ] && gofmt -w "${go[@]}" 2>/dev/null || true
  elif [ -f go.mod ]; then
    gofmt -w . 2>/dev/null || true
  fi
fi

# Rust — rustfmt per changed file when scoped; cargo fmt (whole crate) when unscoped.
if [ "$SCOPED" = 1 ]; then
  if command -v rustfmt >/dev/null 2>&1 && [ "${#rs[@]}" -gt 0 ]; then
    rustfmt "${rs[@]}" 2>/dev/null || true
  fi
elif [ -f Cargo.toml ] && command -v cargo >/dev/null 2>&1; then
  cargo fmt 2>/dev/null || true
fi

# Surface unresolved lint problems back to Claude so it can fix them.
if [ -n "${out:-}" ] && echo "$out" | grep -qiE 'error|warning|problem'; then
  echo "Linter reported issues — fix before finishing:"
  echo "$out" | tail -30
fi

exit 0
