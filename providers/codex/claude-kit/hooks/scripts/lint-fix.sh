#!/usr/bin/env bash
# Resolve the physical project root. Codex may launch hooks from a nested session cwd and does not
# guarantee CKIT_PROJECT_ROOT. Never follow provider-state/control symlinks while choosing a root.
_CKIT_ROOT_EXPLICIT=0
if [ -n "${CKIT_PROJECT_ROOT:-}" ]; then
  _CKIT_ROOT_START="$CKIT_PROJECT_ROOT"
  _CKIT_ROOT_EXPLICIT=1
else
  _CKIT_ROOT_START="$PWD"
fi
ROOT="$(cd -P -- "$_CKIT_ROOT_START" 2>/dev/null && pwd -P)" || exit 0
while :; do
  if [ -L "$ROOT/.ckit" ] || [ -L "$ROOT/.codex" ] || [ -L "$ROOT/.git" ] || \
     [ -L "$ROOT/.codex/hooks.json" ] || [ -L "$ROOT/.ckit/config" ] || \
     [ -L "$ROOT/.ckit/config/init-options.json" ]; then
    exit 0
  fi
  if { [ -d "$ROOT/.codex" ] && [ -f "$ROOT/.codex/hooks.json" ]; } || \
     { [ -d "$ROOT/.ckit/config" ] && [ -f "$ROOT/.ckit/config/init-options.json" ]; } || \
     [ -d "$ROOT/.git" ] || [ -f "$ROOT/.git" ]; then
    break
  fi
  [ "$_CKIT_ROOT_EXPLICIT" -eq 0 ] || exit 0
  [ "$ROOT" != "/" ] || exit 0
  ROOT="${ROOT%/*}"
  [ -n "$ROOT" ] || ROOT="/"
done
unset _CKIT_ROOT_EXPLICIT _CKIT_ROOT_START
# Stop hook: auto-fix lint/format issues using whatever tooling the project already has.
# Stack-detecting and best-effort. It requests at most one Stop continuation when a proven lint
# issue remains; no-op if no tooling is found.
#
# Scope (P0-3): by DEFAULT only the files changed in this repo are formatted, so a Stop never rewrites
# files the user never touched. Set CKIT_AUTOFIX=1 (legacy CKIT_AUTOFIX is accepted) to
# restore whole-repo formatting. When git is
# unavailable or this isn't a work tree, it falls back to whole-repo (best-effort).
# Tools: ruff (Python), gofmt/rustfmt (Go/Rust), and an npm "lint" script (JS/TS).
#
# Feedback path (Codex >= 2.1.163): unresolved lint problems are returned as
# top-level decision/reason JSON so the host continues the turn and the model can fix them before
# finishing.
# stop_hook_active gates it to ONE nudge per stop chain, per the hooks reference.
set -u
if [ -t 0 ]; then INPUT=""; else INPUT="$(cat 2>/dev/null || true)"; fi
cd "$ROOT" 2>/dev/null || exit 0

STOP_ACTIVE="false"
if command -v jq >/dev/null 2>&1; then
  STOP_ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || true)"
fi

out=""

# Whole-repo only when explicitly opted in, or when we can't scope via git.
SCOPED=1
[ "${CKIT_AUTOFIX:-${CKIT_AUTOFIX:-0}}" = "1" ] && SCOPED=0
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

# JavaScript / TypeScript -- the project's own "lint" script (can't be scoped per-file generically, so
# in scoped mode run it only when JS/TS actually changed).
if [ -f package.json ] && command -v npm >/dev/null 2>&1 && grep -q '"lint"' package.json 2>/dev/null; then
  if [ "$SCOPED" = 0 ] || [ "${#js[@]}" -gt 0 ]; then
    out="$(npm run -s lint --if-present 2>&1)"
  fi
fi

# Python -- ruff (fix + format)
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

# Rust -- rustfmt per changed file when scoped; cargo fmt (whole crate) when unscoped.
if [ "$SCOPED" = 1 ]; then
  if command -v rustfmt >/dev/null 2>&1 && [ "${#rs[@]}" -gt 0 ]; then
    rustfmt "${rs[@]}" 2>/dev/null || true
  fi
elif [ -f Cargo.toml ] && command -v cargo >/dev/null 2>&1; then
  cargo fmt 2>/dev/null || true
fi

# Surface unresolved lint problems back to Codex so it can fix them (one nudge per chain).
if [ "$STOP_ACTIVE" != "true" ] && [ -n "${out:-}" ] && echo "$out" | grep -qiE 'error|warning|problem'; then
  MSG="Linter reported issues -- fix before finishing:
$(echo "$out" | tail -30)"
  if command -v jq >/dev/null 2>&1; then
    # stdout must be ONLY the JSON object for Codex to process it.
    jq -n --arg reason "$MSG" '{decision: "block", reason: $reason}'
  fi
fi

exit 0
