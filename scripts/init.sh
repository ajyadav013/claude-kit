#!/usr/bin/env bash
# claude-kit scaffolder.
#
# Copies the claude-kit payload (rules, agents, skills, hooks, templates) into a target
# project's .claude/ directory and drops a generic CLAUDE.md at the project root.
#
# Used by the /claude-kit:init slash command (plugin) and runnable directly from a checkout.
# The pip CLI (`claude-kit init`) performs the same scaffolding in Python.
#
# Usage:  init.sh [TARGET_DIR] [--force] [--minimal] [--no-hooks]
#   TARGET_DIR  project to scaffold into (default: $CLAUDE_PROJECT_DIR or current dir)
#   --force     overwrite existing CLAUDE.md / settings.json (otherwise written as *.example)
#   --minimal   only CLAUDE.md + rules/ (skip agents, skills, hooks, memory)
#   --no-hooks  skip installing hook scripts and settings.json
set -euo pipefail

FORCE=0; MINIMAL=0; NO_HOOKS=0; TARGET=""
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --minimal) MINIMAL=1 ;;
    --no-hooks) NO_HOOKS=1 ;;
    -*) echo "unknown flag: $arg" >&2; exit 2 ;;
    *) TARGET="$arg" ;;
  esac
done
TARGET="${TARGET:-${CLAUDE_PROJECT_DIR:-$PWD}}"

# Resolve the kit source: plugin root when installed as a plugin, else this checkout's root.
SRC="${CLAUDE_PLUGIN_ROOT:-}"
if [ -z "$SRC" ]; then
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
for d in rules templates; do
  [ -d "$SRC/$d" ] || { echo "error: kit source incomplete (missing $SRC/$d)" >&2; exit 1; }
done

DEST="$TARGET/.claude"
mkdir -p "$DEST"
echo "claude-kit: scaffolding into $TARGET"

copy_root_file() {  # src, dest, label
  local src="$1" dest="$2" label="$3"
  if [ -f "$dest" ] && [ "$FORCE" -ne 1 ]; then
    cp "$src" "${dest}.claude-kit"
    echo "  • $label exists — wrote ${dest##*/}.claude-kit (use --force to overwrite)"
  else
    cp "$src" "$dest"; echo "  • $label installed"
  fi
}

# Rules + the generic CLAUDE.md are always installed.
rm -rf "$DEST/rules"; cp -R "$SRC/rules" "$DEST/rules"; echo "  • rules/ ($(ls "$DEST/rules" | wc -l | tr -d ' ') files)"
copy_root_file "$SRC/templates/CLAUDE.md" "$TARGET/CLAUDE.md" "CLAUDE.md"
cp "$SRC/templates/CONTINUITY.template.md" "$DEST/CONTINUITY.template.md"

if [ "$MINIMAL" -ne 1 ]; then
  rm -rf "$DEST/agents"; cp -R "$SRC/agents" "$DEST/agents"; echo "  • agents/ ($(ls "$DEST/agents" | wc -l | tr -d ' ') files)"
  rm -rf "$DEST/skills"; cp -R "$SRC/skills" "$DEST/skills"; echo "  • skills/ ($(ls -d "$DEST"/skills/*/ | wc -l | tr -d ' ') skills)"
  if [ ! -d "$DEST/agent-memory" ]; then
    cp -R "$SRC/templates/agent-memory" "$DEST/agent-memory"; echo "  • agent-memory/ seed"
  fi
fi

if [ "$MINIMAL" -ne 1 ] && [ "$NO_HOOKS" -ne 1 ]; then
  mkdir -p "$DEST/hooks"; cp "$SRC"/hooks/scripts/*.sh "$DEST/hooks/" 2>/dev/null || true
  chmod +x "$DEST"/hooks/*.sh 2>/dev/null || true
  echo "  • hooks/ ($(ls "$DEST"/hooks/*.sh 2>/dev/null | wc -l | tr -d ' ') scripts)"
  copy_root_file "$SRC/templates/settings.json" "$DEST/settings.json" "settings.json"
fi

echo "claude-kit: done. Open the project in Claude Code; CLAUDE.md and .claude/ are now active."
